from __future__ import annotations

import polars as pl

from huginmail.classify import classify_rules
from huginmail.confirm import ConfirmSession
from huginmail.export import export_manifest, manifest_frame
from huginmail.models import SenderRule
from huginmail.summary import render_summary
from huginmail.sync import sync_folder
from conftest import FakeImapSource, raw


def _seed(store, tax):
    src = FakeImapSource({"INBOX": (10, [
        raw(1, "a", subject="SALE 50% off", from_addr="promo@shop.com"),
        raw(2, "b", subject="your invoice", from_addr="bank@bank.com"),
        raw(3, "c", subject="hello there", from_addr="bob@friend.com"),
    ])})
    sync_folder(store, src, tax, "INBOX")


def test_keyword_rule_classifies(store, tax):
    _seed(store, tax)
    res = classify_rules(store, tax)
    # msg1 -> junk (keyword), msg2 -> receipt (keyword), msg3 uncovered
    assert res.written == 2 and res.uncovered == 1


def test_sender_rule_takes_precedence(store, tax):
    _seed(store, tax)
    ConfirmSession(store, tax).set_rule("promo@shop.com", "addr", "keep")
    classify_rules(store, tax)
    df = manifest_frame(store, tax)
    row = df.filter(pl.col("from_addr") == "promo@shop.com")
    assert row["tag"][0] == "keep" and row["method"][0] == "sender_rule"


def test_reclassify_is_idempotent(store, tax):
    _seed(store, tax)
    classify_rules(store, tax)
    second = classify_rules(store, tax)
    assert second.written == 0 and second.unchanged == 2


def test_manifest_export_writes_twin(store, tax, tmp_path):
    _seed(store, tax)
    classify_rules(store, tax)
    parquet, csv = export_manifest(store, tax, tmp_path)
    assert parquet.exists() and csv.exists()
    assert pl.read_parquet(parquet).height == 2


def test_invalid_rule_marked_stale(store, tax):
    _seed(store, tax)
    store.upsert_rule(SenderRule(key="bob@friend.com", scope="addr", tag="ghost"))
    classify_rules(store, tax)
    row = store._conn.execute(
        "SELECT stale FROM sender_rules WHERE key='bob@friend.com'"
    ).fetchone()
    assert row["stale"] == 1


def test_summary_reports_coverage_and_methods(store, tax):
    _seed(store, tax)
    classify_rules(store, tax)
    md = render_summary(store, tax)
    assert "## Coverage" in md
    assert "Classified: 2" in md
    assert "keyword_rule" in md
    assert "Unclassified: 1" in md
