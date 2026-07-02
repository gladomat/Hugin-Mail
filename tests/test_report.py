from __future__ import annotations

from huginmail.report import render_markdown, top_senders, write_sender_report
from huginmail.sync import sync_folder
from conftest import FakeImapSource, raw


def _seed(store, tax):
    src = FakeImapSource({"INBOX": (10, [
        raw(1, "a", subject="SALE 50% off", from_addr="promo@shop.com"),
        raw(2, "b", subject="Deal", from_addr="promo@shop.com", text="unsubscribe"),
        raw(3, "c", subject="hi", from_addr="bob@friend.com"),
    ])})
    sync_folder(store, src, tax, "INBOX")


def test_top_senders_ordered_by_count(store, tax):
    _seed(store, tax)
    profiles = top_senders(store, top=100)
    assert profiles[0].from_addr == "promo@shop.com"
    assert profiles[0].message_count == 2


def test_dominant_hint_and_examples(store, tax):
    _seed(store, tax)
    top = top_senders(store, top=100)
    promo = next(p for p in top if p.from_addr == "promo@shop.com")
    assert promo.keyword_hint == "junk"
    assert len(promo.example_subjects) >= 1


def test_empty_report(store, tax):
    assert top_senders(store) == []


def test_write_report_file(store, tax, tmp_path):
    _seed(store, tax)
    path = write_sender_report(store, tmp_path, "v1", top=100)
    text = path.read_text()
    assert path.exists()
    assert "promo@shop.com" in text and "Taxonomy version: v1" in text


def test_markdown_escapes_pipes(store, tax):
    from huginmail.models import SenderProfile
    md = render_markdown(
        [SenderProfile(from_addr="a@x.com", from_domain="x.com", message_count=1,
                       example_subjects=("a|b",))],
        "v1", 100,
    )
    assert "a\\|b" in md
