from __future__ import annotations

import pytest

from huginmail.sync import MutationError, _assert_read_only, sync_folder
from conftest import FakeImapSource, raw


def test_sync_indexes_and_hints(store, tax):
    src = FakeImapSource({"INBOX": (10, [
        raw(1, "a", subject="Big SALE 50% off"),
        raw(2, "b", subject="hello"),
    ])})
    res = sync_folder(store, src, tax, "INBOX")
    assert res.fetched == 2 and res.inserted == 2
    assert store.message_count() == 2
    hint = store._conn.execute(
        "SELECT keyword_hint FROM messages WHERE uid=1"
    ).fetchone()[0]
    assert hint == "junk"


def test_sync_uses_body_peek_no_mutation(store, tax):
    src = FakeImapSource({"INBOX": (10, [raw(1, "a")])})
    res = sync_folder(store, src, tax, "INBOX")
    assert all("STORE" not in c and "EXPUNGE" not in c for c in res.command_log)
    assert any("EXAMINE" in c for c in res.command_log)


def test_dedup_by_message_id_across_folders(store, tax):
    src = FakeImapSource({
        "INBOX": (10, [raw(1, "shared")]),
        "Archive": (20, [raw(1, "shared"), raw(2, "unique")]),
    })
    sync_folder(store, src, tax, "INBOX")
    res = sync_folder(store, src, tax, "Archive")
    assert res.deduped == 1 and res.inserted == 1
    assert store.distinct_message_count() == 2


def test_resume_from_cursor(store, tax):
    src = FakeImapSource({"INBOX": (10, [raw(1, "a"), raw(2, "b")])})
    sync_folder(store, src, tax, "INBOX")
    # add a new message, resync: only uid>2 fetched
    src._folders["INBOX"] = (10, [raw(1, "a"), raw(2, "b"), raw(3, "c")])
    res = sync_folder(store, src, tax, "INBOX")
    assert res.fetched == 1 and res.inserted == 1
    assert store.message_count() == 3


def test_uidvalidity_rollover_forces_resync(store, tax):
    src = FakeImapSource({"INBOX": (10, [raw(1, "a"), raw(2, "b")])})
    sync_folder(store, src, tax, "INBOX")
    # server rolls uidvalidity; same uids now mean different messages
    src._folders["INBOX"] = (99, [raw(1, "x"), raw(2, "y")])
    res = sync_folder(store, src, tax, "INBOX")
    assert res.resynced and res.uidvalidity == 99
    assert store.message_count() == 2  # old dropped, new indexed


def test_assert_read_only_flags_mutation():
    with pytest.raises(MutationError):
        _assert_read_only(["EXAMINE INBOX", "UID STORE 1 +FLAGS (\\Seen)"])
