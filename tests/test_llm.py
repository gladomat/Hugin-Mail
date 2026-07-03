from __future__ import annotations

from huginmail.classify import classify_llm_batch
from huginmail.config import LlmConfig
from huginmail.llm import (
    PROMPT_VERSION,
    SAMPLING,
    build_payload,
    classify_message,
    load_prompt,
)
from huginmail.models import EmailMessage
from huginmail.sync import sync_folder
from conftest import FakeImapSource, raw


class FakeClient:
    """Canned LLM. `reply` is the raw content; records sampling for assertions."""

    def __init__(self, reply: str, fail_first: bool = False) -> None:
        self.reply = reply
        self.fail_first = fail_first
        self.calls: list[dict] = []

    def complete(self, system: str, user: str, sampling: dict) -> str:
        self.calls.append({"system": system, "user": user, "sampling": sampling})
        if self.fail_first and len(self.calls) == 1:
            return "garbage not json"
        return self.reply


CFG = LlmConfig(model_id="test-model")


def _msg(subject="mystery", snippet="body"):
    return EmailMessage(uid=1, folder="INBOX", uidvalidity=1, message_id="m",
                        from_addr="x@y.com", from_domain="y.com", subject=subject,
                        snippet=snippet)


def test_prompt_has_version_and_loads(tax):
    assert PROMPT_VERSION in load_prompt() or "{taxonomy}" in load_prompt()


def test_sampling_profile_sent(tax):
    c = FakeClient('{"tag":"keep","confidence":0.9,"rationale":"personal"}')
    classify_message(c, tax, _msg(), CFG)
    assert c.calls[0]["sampling"] == SAMPLING


def test_valid_response_parsed(tax):
    c = FakeClient('{"tag":"receipt","subtags":["receipt/bank"],'
                   '"confidence":0.8,"rationale":"a statement"}')
    out = classify_message(c, tax, _msg(), CFG)
    assert out.tag == "receipt" and out.subtag == "bank"
    assert out.model_id == "test-model" and out.prompt_version == PROMPT_VERSION


def test_retry_once_then_succeeds(tax):
    c = FakeClient('{"tag":"keep","confidence":0.7,"rationale":"ok"}', fail_first=True)
    out = classify_message(c, tax, _msg(), CFG)
    assert out.tag == "keep" and len(c.calls) == 2


def test_invalid_tag_becomes_unclassified(tax):
    c = FakeClient('{"tag":"nonsense","confidence":0.9,"rationale":"x"}')
    out = classify_message(c, tax, _msg(), CFG)
    assert out.tag == "unclassified"


def test_two_failures_become_unclassified(tax):
    c = FakeClient("still not json")
    out = classify_message(c, tax, _msg(), CFG)
    assert out.tag == "unclassified" and len(c.calls) == 2


def test_json_extracted_from_noise(tax):
    c = FakeClient('here you go: {"tag":"junk","confidence":0.6,"rationale":"ad"} done')
    out = classify_message(c, tax, _msg(), CFG)
    assert out.tag == "junk"


def test_payload_truncation_flagged():
    msg = _msg(snippet="word " * 500)
    payload, truncated = build_payload(msg, budget=60)
    assert truncated and len(payload) < len("word " * 500)


def test_payload_not_truncated_when_small():
    _, truncated = build_payload(_msg(snippet="short"), budget=300)
    assert truncated is False


def test_batch_classifies_only_uncovered(store, tax):
    src = FakeImapSource({"INBOX": (10, [
        raw(1, "a", subject="your invoice", from_addr="b@bank.com"),  # keyword rule
        raw(2, "b", subject="mystery meeting", from_addr="c@corp.com"),  # LLM
    ])})
    sync_folder(store, src, tax, "INBOX")
    from huginmail.classify import classify_rules
    classify_rules(store, tax)  # covers msg1
    c = FakeClient('{"tag":"keep","confidence":0.9,"rationale":"work"}')
    res = classify_llm_batch(store, tax, c, CFG)
    assert res.called == 1  # only the uncovered msg2
    assert store.latest_tag("INBOX", 2, tax.content_hash) == "keep"


def test_batch_limit_respected(store, tax):
    msgs = [raw(i, f"m{i}", subject=f"thing {i}", from_addr=f"u{i}@z.com")
            for i in range(1, 6)]
    sync_folder(store, FakeImapSource({"INBOX": (10, msgs)}), tax, "INBOX")
    c = FakeClient('{"tag":"keep","confidence":0.5,"rationale":"x"}')
    res = classify_llm_batch(store, tax, c, CFG, limit=2)
    assert res.called == 2
