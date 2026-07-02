"""Pass 0: read-only IMAP sync. EXAMINE + BODY.PEEK, never mutates the server.

The engine works against the `ImapSource` protocol so it is testable without a
live server. `ImapToolsSource` is the real adapter (imap-tools); tests inject a
fake. Every source records the IMAP commands it issues into `command_log` — the
sync asserts the log is mutation-free, satisfying the zero-mutation guarantee.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Protocol, runtime_checkable

from .config import Config
from .hints import keyword_hint
from .models import EmailMessage, TagTaxonomy
from .store import Store

# Commands that would change server state. Their presence in a source's command
# log is a hard failure — v1 is strictly read-only (PRD §3, §16).
MUTATING_COMMANDS = frozenset(
    {"STORE", "UID STORE", "EXPUNGE", "COPY", "UID COPY", "MOVE", "UID MOVE",
     "APPEND", "CREATE", "DELETE", "RENAME", "SETACL", "SUBSCRIBE"}
)


@dataclass(frozen=True)
class RawMessage:
    uid: int
    message_id: str
    from_addr: str
    to: str
    subject: str
    date: datetime | None
    size: int
    text: str
    headers_blob: str


@runtime_checkable
class ImapSource(Protocol):
    command_log: list[str]

    def examine(self, folder: str) -> int:
        """Select folder read-only (EXAMINE); return its UIDVALIDITY."""

    def fetch(self, folder: str, min_uid: int) -> Iterable[RawMessage]:
        """Fetch headers + text (BODY.PEEK) for UIDs > min_uid, ascending."""


class MutationError(RuntimeError):
    """A mutating IMAP command was observed. Aborts the read-only guarantee."""


@dataclass
class SyncResult:
    folder: str
    fetched: int = 0
    inserted: int = 0
    deduped: int = 0
    uidvalidity: int = 0
    resynced: bool = False
    command_log: list[str] = field(default_factory=list)


def _snippet(text: str, cap: int = 500) -> str:
    return " ".join(text.split())[:cap]


def _domain(addr: str) -> str:
    return addr.rsplit("@", 1)[-1].lower() if "@" in addr else ""


def build_email(folder: str, uidvalidity: int, raw: RawMessage) -> EmailMessage:
    return EmailMessage(
        uid=raw.uid,
        folder=folder,
        uidvalidity=uidvalidity,
        message_id=raw.message_id,
        from_addr=raw.from_addr.lower(),
        from_domain=_domain(raw.from_addr),
        to=raw.to,
        subject=raw.subject,
        date=raw.date,
        size=raw.size,
        snippet=_snippet(raw.text),
        headers_hash=hashlib.sha256(raw.headers_blob.encode()).hexdigest()[:16],
    )


def _assert_read_only(log: Iterable[str]) -> None:
    for cmd in log:
        head = cmd.strip().upper()
        for bad in MUTATING_COMMANDS:
            if head == bad or head.startswith(bad + " "):
                raise MutationError(f"Mutating IMAP command issued: {cmd!r}")


def sync_folder(
    store: Store,
    source: ImapSource,
    tax: TagTaxonomy,
    folder: str,
    full: bool = False,
) -> SyncResult:
    """Index one folder. Resumable via the stored cursor; forces resync on a
    UIDVALIDITY change. Dedups by Message-ID across folders (first-seen wins)."""
    uidvalidity = source.examine(folder)
    cursor = store.get_cursor(folder)

    resynced = False
    min_uid = 0
    if cursor is not None and cursor["uidvalidity"] != uidvalidity:
        # UIDVALIDITY rollover: prior UIDs are meaningless; drop + full resync.
        store.drop_folder(folder)
        resynced = True
    elif cursor is not None and not full:
        min_uid = cursor["last_uid"]

    seen_ids = _existing_message_ids(store)
    to_insert: list[EmailMessage] = []
    hints: dict[int, str] = {}
    fetched = deduped = 0
    max_uid = min_uid

    for raw in source.fetch(folder, min_uid):
        fetched += 1
        max_uid = max(max_uid, raw.uid)
        if raw.message_id and raw.message_id in seen_ids:
            deduped += 1
            continue
        if raw.message_id:
            seen_ids.add(raw.message_id)
        msg = build_email(folder, uidvalidity, raw)
        to_insert.append(msg)
        hint = keyword_hint(msg, tax)
        if hint:
            hints[msg.uid] = hint

    _assert_read_only(source.command_log)

    inserted = store.upsert_messages(to_insert, hints)
    store.set_cursor(folder, uidvalidity, max_uid, complete=True)

    return SyncResult(
        folder=folder, fetched=fetched, inserted=inserted, deduped=deduped,
        uidvalidity=uidvalidity, resynced=resynced, command_log=list(source.command_log),
    )


def _existing_message_ids(store: Store) -> set[str]:
    rows = store._conn.execute(
        "SELECT DISTINCT message_id FROM messages"
    ).fetchall()
    return {r[0] for r in rows if r[0]}
