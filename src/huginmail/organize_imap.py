"""Write-capable IMAP adapter for `hugin organize`. Deliberately separate from
the read-only `ImapToolsSource` (`sync_imap.py`) so the sync/index path keeps
its `MUTATING_COMMANDS` guarantee — only this module ever mutates a mailbox.

Provider-agnostic: uses standard IMAP MOVE/COPY (imap-tools), no X-GM-LABELS.
imap-tools is imported lazily so importing this module needs no live host."""

from __future__ import annotations

from typing import Iterable


class ImapWriteSource:
    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        from imap_tools import MailBox

        self.command_log: list[str] = []
        self._mailbox = MailBox(host, port).login(username, password)

    def select(self, folder: str) -> int:
        """Select `folder` read-write; return its UIDVALIDITY (rollover guard)."""
        self.command_log.append(f"SELECT {folder}")
        self._mailbox.folder.set(folder, readonly=False)
        info = self._mailbox.folder.status(folder, options=("UIDVALIDITY",))
        return int(info["UIDVALIDITY"])

    def existing_uids(self, folder: str) -> set[int]:
        """UIDs currently present in `folder` — lets apply skip already-moved
        messages (idempotency) and never target a stale UID."""
        self._mailbox.folder.set(folder, readonly=True)
        self.command_log.append(f"UID SEARCH {folder} ALL")
        return {int(u) for u in self._mailbox.uids("ALL")}

    def ensure_folder(self, name: str) -> None:
        if not self._mailbox.folder.exists(name):
            self.command_log.append(f"CREATE {name}")
            self._mailbox.folder.create(name)

    def apply(self, uids: Iterable[int], dest: str, mechanism: str) -> None:
        """Move (COPY+\\Deleted+EXPUNGE) or copy `uids` into `dest`. Source folder
        must already be selected read-write via `select()`."""
        uid_list = [str(u) for u in uids]
        if not uid_list:
            return
        self.command_log.append(f"{mechanism.upper()} {uid_list} -> {dest}")
        if mechanism == "move":
            self._mailbox.move(uid_list, dest)
        elif mechanism == "copy":
            self._mailbox.copy(uid_list, dest)
        else:  # pragma: no cover - guarded by config Literal
            raise ValueError(f"unknown mechanism {mechanism!r}")

    def close(self) -> None:
        try:
            self._mailbox.logout()
        except Exception:
            pass
