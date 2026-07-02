from __future__ import annotations

import pytest

from huginmail.hints import keyword_hint
from huginmail.models import TagNode, TagTaxonomy
from huginmail.sync import RawMessage, build_email
from huginmail.taxonomy import (
    TaxonomyBudgetError,
    check_budget,
    load_taxonomy,
    render_prompt,
)


def test_load_v1_has_seed_tags(tax):
    names = {t.name for t in tax.tags}
    assert {"keep", "receipt", "notification", "newsletter", "junk", "unclassified"} <= names


def test_hash_is_stable_across_loads():
    a = load_taxonomy("v1")
    b = load_taxonomy("v1")
    assert a.content_hash == b.content_hash and a.content_hash


def test_budget_passes_for_v1(tax):
    assert check_budget(tax) <= 1200


def test_budget_fails_when_over():
    big = TagTaxonomy(
        version="big",
        tags=tuple(
            TagNode(name=f"t{i}", definition="x " * 100) for i in range(50)
        ),
    )
    with pytest.raises(TaxonomyBudgetError):
        check_budget(big, budget=1200)


def test_render_prompt_lists_every_tag(tax):
    rendered = render_prompt(tax)
    for t in tax.tags:
        assert t.name in rendered


def _msg(subject="", from_addr="a@x.com", text=""):
    return build_email("INBOX", 1, RawMessage(
        uid=1, message_id="m", from_addr=from_addr, to="", subject=subject,
        date=None, size=0, text=text, headers_blob="h"))


def test_keyword_hint_matches_junk(tax):
    assert keyword_hint(_msg(subject="Big SALE 50% off"), tax) == "junk"


def test_keyword_hint_matches_receipt(tax):
    assert keyword_hint(_msg(subject="Your invoice is ready"), tax) == "receipt"


def test_keyword_hint_none_when_no_match(tax):
    assert keyword_hint(_msg(subject="hello friend"), tax) is None
