from __future__ import annotations

from huginmail.config import LlmConfig
from huginmail.llm import classify_message, sampling_for
from huginmail.models import EmailMessage


class Rec:
    def __init__(self):
        self.calls = []

    def complete(self, system, user, sampling):
        self.calls.append(system)
        return '{"tag":"keep","confidence":0.9,"rationale":"friend mail"}'


def _msg():
    return EmailMessage(uid=1, folder="INBOX", uidvalidity=1, message_id="m",
                        from_addr="x@y.com", from_domain="y.com", subject="hi")


def test_defaults_terse_and_75():
    cfg = LlmConfig()
    assert cfg.rationale == "terse" and cfg.max_tokens == 75


def test_max_tokens_from_config():
    assert sampling_for(LlmConfig(max_tokens=48))["max_tokens"] == 48


def test_terse_instruction_in_prompt(tax):
    c = Rec()
    out = classify_message(c, tax, _msg(), LlmConfig(rationale="terse"))
    assert "at most 6 words" in c.calls[0]
    assert out.prompt_version.endswith("+terse")


def test_full_instruction_in_prompt(tax):
    c = Rec()
    out = classify_message(c, tax, _msg(), LlmConfig(rationale="full"))
    assert "one-sentence" in c.calls[0]
    assert out.prompt_version.endswith("+full")


def test_off_instruction_in_prompt(tax):
    c = Rec()
    out = classify_message(c, tax, _msg(), LlmConfig(rationale="off"))
    assert "empty string" in c.calls[0]
    assert out.prompt_version.endswith("+off")
