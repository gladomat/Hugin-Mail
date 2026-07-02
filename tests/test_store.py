from __future__ import annotations

from datetime import datetime

from huginmail.models import ClassificationRecord, EmailMessage
from huginmail.store import Store


def _msg(uid, msgid, folder="INBOX"):
    return EmailMessage(
        uid=uid, folder=folder, uidvalidity=1, message_id=msgid,
        from_addr="a@x.com", from_domain="x.com", subject="s", snippet="body",
    )


def test_init_schema_idempotent(tmp_path):
    s = Store(tmp_path / "d.sqlite")
    s.init_schema()
    s.init_schema()  # second call must not raise
    assert s.message_count() == 0
    s.close()


def test_upsert_and_count(store):
    n = store.upsert_messages([_msg(1, "a"), _msg(2, "b")], {1: "junk"})
    assert n == 2
    assert store.message_count() == 2
    assert store.distinct_message_count() == 2


def test_upsert_conflict_updates(store):
    store.upsert_messages([_msg(1, "a")])
    store.upsert_messages([_msg(1, "a")])
    assert store.message_count() == 1


def test_cursor_roundtrip(store):
    assert store.get_cursor("INBOX") is None
    store.set_cursor("INBOX", uidvalidity=42, last_uid=99, complete=True)
    cur = store.get_cursor("INBOX")
    assert cur["uidvalidity"] == 42 and cur["last_uid"] == 99 and cur["complete"] == 1


def test_drop_folder(store):
    store.upsert_messages([_msg(1, "a"), _msg(2, "b")])
    store.drop_folder("INBOX")
    assert store.message_count() == 0


def test_classification_count(store):
    rec = ClassificationRecord(
        uid=1, folder="INBOX", tag="junk", method="keyword_rule",
        taxonomy_version="v1", taxonomy_hash="h", created_at=datetime(2026, 1, 1),
    )
    store.add_classification(rec)
    assert store.classification_count() == 1
