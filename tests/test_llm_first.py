from __future__ import annotations

from huginmail.classify import classify_llm_batch, classify_rules
from huginmail.config import Config, LlmConfig
from huginmail.models import EmailMessage
from huginmail.rules import Resolver
from huginmail.summary import render_summary
from huginmail.sync import sync_folder
from conftest import FakeImapSource, raw


def _msg(subject="your invoice", from_addr="b@bank.com"):
    return EmailMessage(uid=1, folder="INBOX", uidvalidity=1, message_id="m",
                        from_addr=from_addr, from_domain="bank.com", subject=subject)


class FakeClient:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def complete(self, system, user, sampling):
        self.calls.append(user)
        return self.reply


CFG = LlmConfig(model_id="t")


# --- config defaults ---------------------------------------------------
def test_config_defaults_advisory_and_threshold(tmp_path):
    from huginmail.config import load_config
    c = load_config(tmp_path)
    assert c.keyword_rules_authoritative is False
    assert c.llm.confidence_threshold == 0.7


# --- advisory resolver -------------------------------------------------
def test_resolver_advisory_skips_keyword(tax):
    # "your invoice" would hit the receipt keyword rule when authoritative
    auth = Resolver([], tax, keyword_authoritative=True).resolve(_msg())
    adv = Resolver([], tax, keyword_authoritative=False).resolve(_msg())
    assert auth is not None and auth.method == "keyword_rule"
    assert adv is None  # advisory → falls through to the LLM


def test_classify_rules_advisory_leaves_uncovered(store, tax):
    sync_folder(store, FakeImapSource({"INBOX": (10, [
        raw(1, "a", subject="your invoice", from_addr="b@bank.com")])}), tax, "INBOX")
    res = classify_rules(store, tax, keyword_authoritative=False)
    assert res.written == 0 and res.uncovered == 1


# --- abstention --------------------------------------------------------
def test_llm_abstains_below_threshold(store, tax):
    sync_folder(store, FakeImapSource({"INBOX": (10, [
        raw(1, "a", subject="hmm", from_addr="x@y.com")])}), tax, "INBOX")
    c = FakeClient('{"tag":"keep","confidence":0.4,"rationale":"unsure"}')
    classify_llm_batch(store, tax, c, CFG, keyword_authoritative=False,
                       confidence_threshold=0.7)
    # confidence 0.4 < 0.7 → recorded as unclassified
    assert store.latest_tag("INBOX", 1, tax.content_hash) == "unclassified"


def test_llm_keeps_confident_tag(store, tax):
    sync_folder(store, FakeImapSource({"INBOX": (10, [
        raw(1, "a", subject="hmm", from_addr="x@y.com")])}), tax, "INBOX")
    c = FakeClient('{"tag":"keep","confidence":0.95,"rationale":"clear"}')
    classify_llm_batch(store, tax, c, CFG, keyword_authoritative=False,
                       confidence_threshold=0.7)
    assert store.latest_tag("INBOX", 1, tax.content_hash) == "keep"


def test_advisory_hint_injected_into_prompt(store, tax):
    # invoice → receipt keyword hint should reach the LLM payload as advisory text
    from huginmail.llm import classify_message
    c = FakeClient('{"tag":"receipt","confidence":0.9,"rationale":"ok"}')
    classify_message(c, tax, _msg(subject="your invoice"), CFG)
    assert "Keyword hint (advisory" in c.calls[0]
    assert "receipt" in c.calls[0]


# --- summary needs-review ---------------------------------------------
def test_summary_lists_low_confidence(store, tax):
    sync_folder(store, FakeImapSource({"INBOX": (10, [
        raw(1, "a", subject="ambiguous thing", from_addr="x@y.com")])}), tax, "INBOX")
    c = FakeClient('{"tag":"keep","confidence":0.72,"rationale":"maybe"}')
    classify_llm_batch(store, tax, c, CFG, keyword_authoritative=False,
                       confidence_threshold=0.7)
    md = render_summary(store, tax)
    assert "## Needs review" in md
    assert "ambiguous thing"[:60] in md
