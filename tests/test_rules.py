from __future__ import annotations

from datetime import datetime

from huginmail.models import EmailMessage, SenderRule
from huginmail.rules import Resolver, valid_leaves


def _msg(from_addr="a@x.com", domain="x.com", subject=""):
    return EmailMessage(uid=1, folder="INBOX", uidvalidity=1, message_id="m",
                        from_addr=from_addr, from_domain=domain, subject=subject)


def _rule(key, scope, tag, subtag=None):
    return SenderRule(key=key, scope=scope, tag=tag, subtag=subtag)


def test_valid_leaves_includes_subtags(tax):
    leaves = valid_leaves(tax)
    assert "receipt" in leaves and "receipt/bank" in leaves


def test_address_rule_wins_over_domain(tax):
    rules = [_rule("a@x.com", "addr", "keep"), _rule("x.com", "domain", "junk")]
    r = Resolver(rules, tax).resolve(_msg())
    assert r.tag == "keep" and r.method == "sender_rule"


def test_domain_rule_applies_when_no_address_rule(tax):
    r = Resolver([_rule("x.com", "domain", "newsletter")], tax).resolve(_msg())
    assert r.tag == "newsletter" and r.method == "sender_rule"


def test_keyword_rule_when_no_sender_rule(tax):
    r = Resolver([], tax).resolve(_msg(subject="your invoice"))
    assert r.tag == "receipt" and r.method == "keyword_rule"


def test_unresolved_returns_none(tax):
    assert Resolver([], tax).resolve(_msg(subject="hello")) is None


def test_invalid_leaf_treated_as_undecided(tax):
    res = Resolver([_rule("a@x.com", "addr", "nonsuch")], tax)
    assert res.resolve(_msg(subject="hi")) is None
    assert len(res.invalid) == 1


def test_subtag_leaf_resolves(tax):
    r = Resolver([_rule("a@x.com", "addr", "receipt", "bank")], tax).resolve(_msg())
    assert r.tag == "receipt" and r.subtag == "bank"
