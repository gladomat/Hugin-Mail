from __future__ import annotations

import logging

from huginmail.classify import classify_llm_batch
from huginmail.config import LlmConfig
from huginmail.log import configure
from huginmail.sync import sync_folder
from conftest import FakeImapSource, raw


def test_configure_sets_level():
    configure(verbosity=1)
    assert logging.getLogger("huginmail").level == logging.DEBUG
    configure(quiet=True)
    assert logging.getLogger("huginmail").level == logging.WARNING
    configure()
    assert logging.getLogger("huginmail").level == logging.INFO


def test_sync_on_fetch_callback(store, tax):
    seen = []
    src = FakeImapSource({"INBOX": (10, [raw(1, "a"), raw(2, "b"), raw(3, "c")])})
    sync_folder(store, src, tax, "INBOX", on_fetch=seen.append)
    assert seen == [1, 2, 3]  # called per message with running count


class _C:
    def complete(self, s, u, samp):
        return '{"tag":"keep","confidence":0.9,"rationale":"x"}'


def test_classify_on_item_callback(store, tax):
    sync_folder(store, FakeImapSource({"INBOX": (10, [
        raw(1, "a", subject="mystery", from_addr="z@z.com"),
        raw(2, "b", subject="enigma", from_addr="y@y.com")])}), tax, "INBOX")
    events = []
    classify_llm_batch(store, tax, _C(), LlmConfig(), keyword_authoritative=False,
                       on_item=lambda n, tag, conf: events.append((n, tag, conf)))
    assert [e[0] for e in events] == [1, 2]
    assert all(e[1] == "keep" for e in events)
