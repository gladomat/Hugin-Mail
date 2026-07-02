"""Real IMAP adapter (imap-tools). Read-only: EXAMINE + BODY.PEEK only.

Kept separate from sync.py so the sync engine stays testable without a server.
imap-tools is imported lazily so importing this module never requires a live host.
"""

from __future__ import annotations

from typing import Iterable

from .sync import RawMessage


class ImapToolsSource:
    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        from imap_tools import MailBox

        self.command_log: list[str] = []
        # imap-tools selects INBOX read-write on login; we re-select each folder
        # read-only (EXAMINE) before fetching, and always fetch mark_seen=False
        # (BODY.PEEK), so \Seen is never set.
        self._mailbox = MailBox(host, port).login(username, password)

    def examine(self, folder: str) -> int:
        self.command_log.append(f"EXAMINE {folder}")
        status = self._mailbox.folder.set(folder, readonly=True)
        # imap-tools exposes UIDVALIDITY via folder status.
        info = self._mailbox.folder.status(folder, options=("UIDVALIDITY",))
        return int(info["UIDVALIDITY"])

    def fetch(self, folder: str, min_uid: int) -> Iterable[RawMessage]:
        from imap_tools import AND

        criteria = AND(uid=f"{min_uid + 1}:*") if min_uid else "ALL"
        self.command_log.append(f"UID FETCH {folder} {min_uid + 1}:* (BODY.PEEK[])")
        for m in self._mailbox.fetch(criteria, mark_seen=False, bulk=True):
            uid = int(m.uid) if m.uid else 0
            if uid <= min_uid:
                continue
            yield RawMessage(
                uid=uid,
                message_id=(m.headers.get("message-id", ("",))[0] or "").strip("<> "),
                from_addr=m.from_ or "",
                to=", ".join(m.to),
                subject=m.subject or "",
                date=m.date,
                size=m.size or 0,
                text=m.text or m.html or "",
                headers_blob=str(sorted(m.headers.items())),
            )

    def close(self) -> None:
        try:
            self._mailbox.logout()
        except Exception:
            pass
