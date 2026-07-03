from __future__ import annotations

import pytest
from textual.widgets import DataTable

from huginmail.classify import classify_llm_batch
from huginmail.config import LlmConfig
from huginmail.confirm import LeafError
from huginmail.review import ReviewSession
from huginmail.review_tui import ReviewApp
from huginmail.sync import sync_folder
from conftest import FakeImapSource, raw


class ConfClient:
    """Assigns 'keep' at a fixed confidence, so band filtering is testable."""
    def __init__(self, conf):
        self.conf = conf

    def complete(self, system, user, sampling):
        return f'{{"tag":"keep","confidence":{self.conf},"rationale":"maybe"}}'


def _seed_and_classify(store, tax, conf=0.8, n=3):
    msgs = [raw(i, f"m{i}", subject=f"thing {i}", from_addr=f"u{i}@z.com")
            for i in range(1, n + 1)]
    sync_folder(store, FakeImapSource({"INBOX": (10, msgs)}), tax, "INBOX")
    classify_llm_batch(store, tax, ConfClient(conf), LlmConfig(),
                       keyword_authoritative=False)


def test_candidates_are_llm_worst_first(store, tax):
    sync_folder(store, FakeImapSource({"INBOX": (10, [
        raw(1, "a", from_addr="a@z.com"), raw(2, "b", from_addr="b@z.com")])}),
        tax, "INBOX")
    # two different confidences
    from huginmail.models import ClassificationRecord
    from datetime import datetime
    for uid, c in [(1, 0.9), (2, 0.6)]:
        store.add_classification(ClassificationRecord(
            uid=uid, folder="INBOX", tag="keep", method="llm",
            taxonomy_version=tax.version, taxonomy_hash=tax.content_hash,
            confidence=c, created_at=datetime(2026, 1, 1)))
    items = ReviewSession(store, tax).candidates()
    assert [i.confidence for i in items] == [0.6, 0.9]  # worst first


def test_band_filter(store, tax):
    _seed_and_classify(store, tax, conf=0.85, n=2)
    assert len(ReviewSession(store, tax, min_conf=0.9, max_conf=1.0).candidates()) == 0
    assert len(ReviewSession(store, tax, min_conf=0.0, max_conf=0.9).candidates()) == 2


def test_retag_writes_human_and_drops_from_band(store, tax):
    _seed_and_classify(store, tax, conf=0.8, n=1)
    s = ReviewSession(store, tax)
    it = s.candidates()[0]
    s.retag(it, "newsletter")
    assert store.latest_tag("INBOX", 1, tax.content_hash) == "newsletter"
    # now method='human', so it leaves the llm review band
    assert s.candidates() == []


def test_retag_rejects_bad_leaf(store, tax):
    _seed_and_classify(store, tax, conf=0.8, n=1)
    s = ReviewSession(store, tax)
    with pytest.raises(LeafError):
        s.retag(s.candidates()[0], "bogus")


def test_make_sender_rule(store, tax):
    _seed_and_classify(store, tax, conf=0.8, n=1)
    s = ReviewSession(store, tax)
    s.make_sender_rule("u1@z.com", "newsletter")
    assert any(r.key == "u1@z.com" and r.tag == "newsletter"
               for r in store.get_rules())


@pytest.mark.asyncio
async def test_tui_retag_via_pilot(store, tax):
    _seed_and_classify(store, tax, conf=0.8, n=2)
    app = ReviewApp(ReviewSession(store, tax))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert len(app.items) == 2
        app.action_retag()
        app.query_one("#entry").value = "junk"
        await pilot.press("enter")
        await pilot.pause()
    # one retagged → one left in the band
    assert len(app.items) == 1
