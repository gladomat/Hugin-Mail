"""SQLite store: operational state, resumable, transactional. Schema mirrors models."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from .models import ClassificationRecord, EmailMessage

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
    from_addr    TEXT PRIMARY KEY,
    tag          TEXT NOT NULL,
    confirmed_by TEXT,
    confirmed_at TEXT
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
