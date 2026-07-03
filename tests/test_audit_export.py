from __future__ import annotations

from huginmail.audit import run_audit, write_audit_report
from huginmail.classify import classify_llm_batch, classify_rules
from huginmail.config import LlmConfig
from huginmail.export import export_rules, render_sieve
from huginmail.models import SenderRule
from huginmail.summary import render_summary
from huginmail.sync import sync_folder
from conftest import FakeImapSource, raw


class _KeepClient:
    """Tags everything 'keep' — sets up a contradiction with junk keywords."""
    def complete(self, s, u, samp):
        return '{"tag":"keep","confidence":0.9,"rationale":"x"}'


def _seed_keep_but_junky(store, tax):
    sync_folder(store, FakeImapSource({"INBOX": (10, [
        raw(1, "a", subject="Big SALE 50% off unsubscribe", from_addr="x@y.com")])}),
        tax, "INBOX")
    classify_llm_batch(store, tax, _KeepClient(), LlmConfig(),
                       keyword_authoritative=False)


# --- #11 audit ---------------------------------------------------------
def test_audit_flags_contradiction(store, tax):
    _seed_keep_but_junky(store, tax)
    findings = run_audit(store, tax)
    assert len(findings) == 1
    f = findings[0]
    assert f.assigned_tag == "keep" and f.suspected_tag == "junk"
    assert "unsubscribe" in f.trigger_keywords or "% off" in f.trigger_keywords


def test_audit_no_finding_when_consistent(store, tax):
    sync_folder(store, FakeImapSource({"INBOX": (10, [
        raw(1, "a", subject="lunch tomorrow?", from_addr="bob@friend.com")])}),
        tax, "INBOX")
    classify_llm_batch(store, tax, _KeepClient(), LlmConfig(),
                       keyword_authoritative=False)
    assert run_audit(store, tax) == []


def test_audit_report_and_summary_count(store, tax, tmp_path):
    _seed_keep_but_junky(store, tax)
    findings = run_audit(store, tax)
    path = write_audit_report(store, findings, tmp_path)
    assert path.exists() and "junk" in path.read_text()
    assert "Open audit findings: 1" in render_summary(store, tax)


def test_audit_regenerates(store, tax):
    _seed_keep_but_junky(store, tax)
    run_audit(store, tax)
    run_audit(store, tax)  # rerun must not duplicate
    assert store.open_finding_count() == 1


# --- #12 export rules --------------------------------------------------
def _rules(store):
    store.upsert_rule(SenderRule(key="noreply@bank.com", scope="addr",
                                 tag="receipt", subtag="bank"))
    store.upsert_rule(SenderRule(key="shop.com", scope="domain", tag="junk"))


def test_export_rules_text(store, tmp_path):
    _rules(store)
    path = export_rules(store, tmp_path, fmt="text")
    text = path.read_text()
    assert path.name == "rules.tsv"
    assert "noreply@bank.com\treceipt/bank" in text
    assert "shop.com\tjunk" in text


def test_export_rules_sieve(store, tmp_path):
    _rules(store)
    path = export_rules(store, tmp_path, fmt="sieve")
    sieve = path.read_text()
    assert path.name == "rules.sieve"
    assert 'require ["fileinto"];' in sieve
    assert 'address :is "from" "noreply@bank.com"' in sieve
    assert 'fileinto "receipt/bank";' in sieve
    assert 'address :domain :is "from" "shop.com"' in sieve
