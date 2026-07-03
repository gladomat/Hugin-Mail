"""SQLite store: operational state, resumable, transactional. Schema mirrors models."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from .models import (
    AuditFinding,
    ClassificationRecord,
    Deferral,
    EmailMessage,
    SenderRule,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    uid          INTEGER NOT NULL,
    folder       TEXT    NOT NULL,
    uidvalidity  INTEGER NOT NULL,
    message_id   TEXT    NOT NULL,
    from_addr    TEXT    NOT NULL,
    from_domain  TEXT    NOT NULL,
    "to"         TEXT    NOT NULL DEFAULT '',
    subject      TEXT    NOT NULL DEFAULT '',
    date         TEXT,
    size         INTEGER NOT NULL DEFAULT 0,
    snippet      TEXT    NOT NULL DEFAULT '',
    headers_hash TEXT    NOT NULL DEFAULT '',
    keyword_hint TEXT,
    PRIMARY KEY (folder, uidvalidity, uid)
);
CREATE INDEX IF NOT EXISTS idx_messages_msgid ON messages(message_id);
CREATE INDEX IF NOT EXISTS idx_messages_from  ON messages(from_addr);

CREATE TABLE IF NOT EXISTS sync_cursor (
    folder      TEXT PRIMARY KEY,
    uidvalidity INTEGER NOT NULL,
    last_uid    INTEGER NOT NULL DEFAULT 0,
    complete    INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS sender_rules (
    key          TEXT NOT NULL,
    scope        TEXT NOT NULL,            -- 'addr' | 'domain'
    tag          TEXT NOT NULL,
    subtag       TEXT,
    stale        INTEGER NOT NULL DEFAULT 0,
    confirmed_by TEXT,
    confirmed_at TEXT,
    PRIMARY KEY (scope, key)
);

CREATE TABLE IF NOT EXISTS deferrals (
    key        TEXT NOT NULL,
    scope      TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (scope, key)
);

CREATE TABLE IF NOT EXISTS classifications (
    uid              INTEGER NOT NULL,
    folder           TEXT    NOT NULL,
    tag              TEXT    NOT NULL,
    subtags          TEXT    NOT NULL DEFAULT '',
    confidence       REAL    NOT NULL DEFAULT 1.0,
    method           TEXT    NOT NULL,
    taxonomy_version TEXT    NOT NULL,
    taxonomy_hash    TEXT    NOT NULL,
    model_id         TEXT,
    prompt_version   TEXT,
    rationale        TEXT,
    truncated        INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_class_uid ON classifications(folder, uid);

CREATE TABLE IF NOT EXISTS audit_findings (
    uid              INTEGER NOT NULL,
    folder           TEXT    NOT NULL,
    assigned_tag     TEXT    NOT NULL,
    suspected_tag    TEXT    NOT NULL,
    trigger_keywords TEXT    NOT NULL,
    resolved         INTEGER NOT NULL DEFAULT 0
);
"""


class Store:
    """Thin SQLite wrapper. Idempotent init; safe to re-open."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

    def init_schema(self) -> None:
        with self._tx() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def close(self) -> None:
        self._conn.close()

    # --- messages -------------------------------------------------------
    def upsert_messages(self, msgs: Iterable[EmailMessage], hints: dict[int, str] | None = None) -> int:
        hints = hints or {}
        rows = [
            (
                m.uid, m.folder, m.uidvalidity, m.message_id, m.from_addr, m.from_domain,
                m.to, m.subject, m.date.isoformat() if m.date else None, m.size,
                m.snippet, m.headers_hash, hints.get(m.uid),
            )
            for m in msgs
        ]
        if not rows:
            return 0
        with self._tx() as c:
            c.executemany(
                """INSERT INTO messages
                   (uid, folder, uidvalidity, message_id, from_addr, from_domain,
                    "to", subject, date, size, snippet, headers_hash, keyword_hint)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(folder, uidvalidity, uid) DO UPDATE SET
                       message_id=excluded.message_id, subject=excluded.subject,
                       snippet=excluded.snippet, keyword_hint=excluded.keyword_hint""",
                rows,
            )
        return len(rows)

    def iter_messages(self) -> Iterator[EmailMessage]:
        cur = self._conn.execute(
            """SELECT uid, folder, uidvalidity, message_id, from_addr, from_domain,
                      "to", subject, date, size, snippet, headers_hash FROM messages"""
        )
        for r in cur:
            yield EmailMessage(
                uid=r["uid"], folder=r["folder"], uidvalidity=r["uidvalidity"],
                message_id=r["message_id"], from_addr=r["from_addr"],
                from_domain=r["from_domain"], to=r["to"], subject=r["subject"],
                date=datetime.fromisoformat(r["date"]) if r["date"] else None,
                size=r["size"], snippet=r["snippet"], headers_hash=r["headers_hash"],
            )

    def message_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

    def distinct_message_count(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(DISTINCT message_id) FROM messages"
        ).fetchone()[0]

    # --- sync cursor ----------------------------------------------------
    def get_cursor(self, folder: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM sync_cursor WHERE folder = ?", (folder,)
        ).fetchone()

    def set_cursor(self, folder: str, uidvalidity: int, last_uid: int, complete: bool) -> None:
        with self._tx() as c:
            c.execute(
                """INSERT INTO sync_cursor (folder, uidvalidity, last_uid, complete, updated_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(folder) DO UPDATE SET
                       uidvalidity=excluded.uidvalidity, last_uid=excluded.last_uid,
                       complete=excluded.complete, updated_at=excluded.updated_at""",
                (folder, uidvalidity, last_uid, int(complete), datetime.now().isoformat()),
            )

    def drop_folder(self, folder: str) -> None:
        """Clear a folder's messages (used on UIDVALIDITY rollover)."""
        with self._tx() as c:
            c.execute("DELETE FROM messages WHERE folder = ?", (folder,))

    # --- classifications ------------------------------------------------
    def add_classification(self, rec: ClassificationRecord) -> None:
        with self._tx() as c:
            c.execute(
                """INSERT INTO classifications
                   (uid, folder, tag, subtags, confidence, method, taxonomy_version,
                    taxonomy_hash, model_id, prompt_version, rationale, truncated, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rec.uid, rec.folder, rec.tag, ",".join(rec.subtags), rec.confidence,
                    rec.method, rec.taxonomy_version, rec.taxonomy_hash, rec.model_id,
                    rec.prompt_version, rec.rationale, int(rec.truncated),
                    rec.created_at.isoformat(),
                ),
            )

    def classification_count(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(DISTINCT folder || ':' || uid) FROM classifications"
        ).fetchone()[0]

    def latest_tag(self, folder: str, uid: int, taxonomy_hash: str) -> str | None:
        row = self._conn.execute(
            """SELECT tag FROM classifications
               WHERE folder=? AND uid=? AND taxonomy_hash=?
               ORDER BY created_at DESC LIMIT 1""",
            (folder, uid, taxonomy_hash),
        ).fetchone()
        return row[0] if row else None

    def manifest_rows(self, taxonomy_hash: str) -> list[sqlite3.Row]:
        """Latest classification per message (for this taxonomy), joined to the
        message. One row per classified (folder, uid)."""
        return self._conn.execute(
            """SELECT m.folder, m.uid, m.message_id, m.from_addr, m.from_domain,
                      m.subject, m.date, c.tag, c.subtags, c.confidence, c.method,
                      c.taxonomy_version, c.model_id, c.prompt_version, c.rationale,
                      c.truncated, c.created_at
               FROM classifications c
               JOIN (SELECT folder, uid, MAX(created_at) mx FROM classifications
                     WHERE taxonomy_hash=? GROUP BY folder, uid) t
                 ON c.folder=t.folder AND c.uid=t.uid AND c.created_at=t.mx
               JOIN messages m ON m.folder=c.folder AND m.uid=c.uid
               WHERE c.taxonomy_hash=?""",
            (taxonomy_hash, taxonomy_hash),
        ).fetchall()

    # --- sender rules ---------------------------------------------------
    def upsert_rule(self, rule: SenderRule) -> None:
        with self._tx() as c:
            c.execute(
                """INSERT INTO sender_rules
                   (key, scope, tag, subtag, stale, confirmed_by, confirmed_at)
                   VALUES (?,?,?,?,0,?,?)
                   ON CONFLICT(scope, key) DO UPDATE SET
                       tag=excluded.tag, subtag=excluded.subtag, stale=0,
                       confirmed_by=excluded.confirmed_by,
                       confirmed_at=excluded.confirmed_at""",
                (
                    rule.key, rule.scope, rule.tag, rule.subtag,
                    rule.confirmed_by,
                    rule.confirmed_at.isoformat() if rule.confirmed_at else None,
                ),
            )
        self.clear_deferral(rule.scope, rule.key)

    def get_rules(self) -> list[SenderRule]:
        rows = self._conn.execute("SELECT * FROM sender_rules").fetchall()
        return [
            SenderRule(
                key=r["key"], scope=r["scope"], tag=r["tag"], subtag=r["subtag"],
                confirmed_by=r["confirmed_by"],
                confirmed_at=datetime.fromisoformat(r["confirmed_at"])
                if r["confirmed_at"] else None,
            )
            for r in rows
        ]

    def mark_rule_stale(self, scope: str, key: str, stale: bool = True) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE sender_rules SET stale=? WHERE scope=? AND key=?",
                (int(stale), scope, key),
            )

    def delete_rule(self, scope: str, key: str) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM sender_rules WHERE scope=? AND key=?", (scope, key))

    # --- deferrals ------------------------------------------------------
    def upsert_deferral(self, d: Deferral) -> None:
        with self._tx() as c:
            c.execute(
                """INSERT INTO deferrals (key, scope, note, created_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(scope, key) DO UPDATE SET note=excluded.note""",
                (d.key, d.scope, d.note,
                 (d.created_at or datetime.now()).isoformat()),
            )

    def get_deferrals(self) -> list[Deferral]:
        rows = self._conn.execute("SELECT * FROM deferrals").fetchall()
        return [
            Deferral(key=r["key"], scope=r["scope"], note=r["note"],
                     created_at=datetime.fromisoformat(r["created_at"]))
            for r in rows
        ]

    def clear_deferral(self, scope: str, key: str) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM deferrals WHERE scope=? AND key=?", (scope, key))

    # --- audit findings -------------------------------------------------
    def replace_audit_findings(self, findings: list[AuditFinding]) -> None:
        """Audit is regenerated each run: clear then repopulate."""
        with self._tx() as c:
            c.execute("DELETE FROM audit_findings")
            c.executemany(
                """INSERT INTO audit_findings
                   (uid, folder, assigned_tag, suspected_tag, trigger_keywords, resolved)
                   VALUES (?,?,?,?,?,?)""",
                [(f.uid, f.folder, f.assigned_tag, f.suspected_tag,
                  ",".join(f.trigger_keywords), int(f.resolved)) for f in findings],
            )

    def get_audit_findings(self) -> list[AuditFinding]:
        rows = self._conn.execute("SELECT * FROM audit_findings").fetchall()
        return [
            AuditFinding(
                uid=r["uid"], folder=r["folder"], assigned_tag=r["assigned_tag"],
                suspected_tag=r["suspected_tag"],
                trigger_keywords=tuple(k for k in r["trigger_keywords"].split(",") if k),
                resolved=bool(r["resolved"]),
            )
            for r in rows
        ]

    def open_finding_count(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM audit_findings WHERE resolved=0"
        ).fetchone()[0]
