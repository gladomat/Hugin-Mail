"""Rule resolution: address → domain → keyword → (LLM) → unclassified.

Shared by `confirm` (coverage projection) and S5 (rules-classify). The resolver
validates each rule's tag leaf against the current taxonomy; an invalid leaf
(e.g. removed by a taxonomy bump before migration) is treated as undecided so no
record is ever emitted against an undefined tag.
"""

from __future__ import annotations

from dataclasses import dataclass

from .hints import keyword_hint
from .models import EmailMessage, Method, SenderRule, TagTaxonomy


@dataclass(frozen=True)
class Resolved:
    tag: str
    subtag: str | None
    method: Method
    confidence: float


def valid_leaves(tax: TagTaxonomy) -> set[str]:
    leaves: set[str] = set()
    for t in tax.tags:
        leaves.add(t.name)
        leaves.update(t.subtags)
    return leaves


class Resolver:
    """Resolves a message to a rule-based tag, or None if an LLM call is needed.

    Sender rules are always authoritative. Keyword rules classify only when
    `keyword_authoritative` is True; otherwise they stay advisory (a hint fed to
    the LLM) and the message falls through to the model (#18)."""

    def __init__(self, rules: list[SenderRule], tax: TagTaxonomy,
                 keyword_authoritative: bool = True) -> None:
        self.tax = tax
        self.keyword_authoritative = keyword_authoritative
        self._leaves = valid_leaves(tax)
        self._by_addr: dict[str, SenderRule] = {}
        self._by_domain: dict[str, SenderRule] = {}
        self.invalid: list[SenderRule] = []
        for r in rules:
            if r.leaf not in self._leaves:
                self.invalid.append(r)
                continue
            (self._by_addr if r.scope == "addr" else self._by_domain)[r.key] = r

    def resolve(self, msg: EmailMessage) -> Resolved | None:
        rule = self._by_addr.get(msg.from_addr) or self._by_domain.get(msg.from_domain)
        if rule is not None:
            return Resolved(rule.tag, rule.subtag, "sender_rule", 1.0)
        if self.keyword_authoritative:
            hint = keyword_hint(msg, self.tax)
            if hint is not None:
                return Resolved(hint, None, "keyword_rule", 1.0)
        return None
