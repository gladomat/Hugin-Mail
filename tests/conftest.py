from __future__ import annotations

from datetime import datetime

import pytest

from huginmail.store import Store
from huginmail.sync import RawMessage
from huginmail.taxonomy import load_taxonomy


@pytest.fixture
def store(tmp_path) -> Store:
    s = Store(tmp_path / "t.sqlite")
    s.init_schema()
    yield s
    s.close()


@pytest.fixture
def tax():
    return load_taxonomy("v1")


class FakeImapSource:
    """In-memory ImapSource. `folders` maps name -> (uidvalidity, [RawMessage])."""

    def __init__(self, folders: dict[str, tuple[int, list[RawMessage]]]) -> None:
        self._folders = folders
        self.command_log: list[str] = []

    def examine(self, folder: str) -> int:
        self.command_log.append(f"EXAMINE {folder}")
        return self._folders[folder][0]

    def fetch(self, folder: str, min_uid: int):
        self.command_log.append(f"UID FETCH {folder} {min_uid + 1}:*")
        for raw in self._folders[folder][1]:
            if raw.uid > min_uid:
                yield raw


def raw(uid: int, msgid: str, subject: str = "", from_addr: str = "a@x.com",
        text: str = "") -> RawMessage:
    return RawMessage(
        uid=uid, message_id=msgid, from_addr=from_addr, to="me@x.com",
        subject=subject, date=datetime(2026, 1, 1), size=100, text=text,
        headers_blob=f"h{uid}",
    )
