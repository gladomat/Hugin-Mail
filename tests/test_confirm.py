from __future__ import annotations

import pytest

from huginmail.confirm import ConfirmSession, LeafError, parse_leaf
from huginmail.sync import sync_folder
from conftest import FakeImapSource, raw


def _seed(store, tax):
    src = FakeImapSource({"INBOX": (10, [
        raw(1, "a", subject="SALE 50% off", from_addr="promo@shop.com"),
        raw(2, "b", subject="Deal", from_addr="promo@shop.com"),
        raw(3, "c", subject="hi", from_addr="bob@friend.com"),
    ])})
    sync_folder(store, src, tax, "INBOX")


def _session(store, tax):
    return ConfirmSession(store, tax, top=100, user="tester")


def test_parse_leaf_valid(tax):
    assert parse_leaf("receipt/bank", tax) == ("receipt", "bank")
    assert parse_leaf("keep", tax) == ("keep", None)


def test_parse_leaf_rejects_unknown(tax):
    with pytest.raises(LeafError):
        parse_leaf("madeup", tax)


def test_queue_has_addr_and_domain_items(store, tax):
    _seed(store, tax)
    items = _session(store, tax).build_queue()
    scopes = {i.scope for i in items}
    assert scopes == {"addr", "domain"}


def test_accept_creates_addr_rule(store, tax):
    _seed(store, tax)
    s = _session(store, tax)
    promo = next(i for i in s.build_queue()
                 if i.scope == "addr" and i.key == "promo@shop.com")
    s.accept(promo)  # hint is junk
    rules = store.get_rules()
    assert any(r.key == "promo@shop.com" and r.tag == "junk" for r in rules)


def test_override_to_subtag(store, tax):
    _seed(store, tax)
    s = _session(store, tax)
    s.set_rule("shop.com", "domain", "receipt/purchase")
    r = next(r for r in store.get_rules() if r.scope == "domain")
    assert r.tag == "receipt" and r.subtag == "purchase"


def test_defer_writes_and_resurfaces(store, tax):
    _seed(store, tax)
    s = _session(store, tax)
    s.defer("bob@friend.com", "addr", "need new tag")
    item = next(i for i in s.build_queue() if i.key == "bob@friend.com")
    assert item.status == "deferred" and item.note == "need new tag"


def test_rule_clears_deferral(store, tax):
    _seed(store, tax)
    s = _session(store, tax)
    s.defer("bob@friend.com", "addr", "later")
    s.set_rule("bob@friend.com", "addr", "keep")
    assert store.get_deferrals() == []


def test_resume_shows_decided_editable(store, tax):
    _seed(store, tax)
    s = _session(store, tax)
    s.set_rule("promo@shop.com", "addr", "junk")
    item = next(i for i in s.build_queue()
                if i.scope == "addr" and i.key == "promo@shop.com")
    assert item.status == "decided" and item.current_leaf == "junk"


def test_coverage_projection(store, tax):
    _seed(store, tax)
    s = _session(store, tax)
    before = s.coverage()
    s.set_rule("bob@friend.com", "addr", "keep")
    after = s.coverage()
    assert after.covered > before.covered
    assert 0.0 <= after.fraction <= 1.0


def test_override_invalid_leaf_raises(store, tax):
    _seed(store, tax)
    with pytest.raises(LeafError):
        _session(store, tax).set_rule("x", "domain", "bogus")
