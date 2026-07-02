"""Deterministic keyword-hint computation (Pass 0). Pure function of taxonomy rules."""

from __future__ import annotations

from .models import EmailMessage, TagTaxonomy


def keyword_hint(msg: EmailMessage, tax: TagTaxonomy) -> str | None:
    """First keyword rule whose keyword appears in any of its fields wins.

    Rule order in the taxonomy is significant: earlier rules take precedence.
    """
    for rule in tax.keyword_rules:
        haystack = " ".join(_field(msg, f) for f in rule.fields).lower()
        if any(kw in haystack for kw in rule.keywords):
            return rule.tag
    return None


def _field(msg: EmailMessage, field: str) -> str:
    if field == "subject":
        return msg.subject
    if field == "from_addr":
        return msg.from_addr
    if field == "snippet":
        return msg.snippet
    return ""
