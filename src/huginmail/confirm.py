"""Pass 2 confirm — session logic, UI-free so it is unit-testable.

Builds the review queue (top-N senders + domain rollup, annotated with existing
decisions), applies accept/override/defer as per-decision idempotent writes, and
projects rule coverage by running the shared Resolver over the index. The Textual
TUI (confirm_tui.py) is a thin driver over this.
"""

from __future__ import annotations

import getpass
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from .models import Deferral, SenderProfile, SenderRule, TagTaxonomy
from .report import top_senders
from .rules import Resolver, valid_leaves
from .store import Store

Status = Literal["undecided", "decided", "deferred", "stale"]

COVERAGE_TARGET = 0.60  # Phase-1b advisory bar; never blocks (Q9).


class LeafError(ValueError):
    """Override target is not a valid taxonomy leaf."""


@dataclass
class QueueItem:
    key: str
    scope: Literal["addr", "domain"]
    label: str
    message_count: int
    hint: str | None
    example_subjects: tuple[str, ...]
    status: Status
    current_leaf: str | None
    note: str = ""


@dataclass
class Coverage:
    total: int
    covered: int

    @property
    def fraction(self) -> float:
        return self.covered / self.total if self.total else 0.0

    @property
    def below_target(self) -> bool:
        return self.fraction < COVERAGE_TARGET


def parse_leaf(leaf: str, tax: TagTaxonomy) -> tuple[str, str | None]:
    leaf = leaf.strip()
    if leaf not in valid_leaves(tax):
        raise LeafError(f"{leaf!r} is not a taxonomy leaf in {tax.version}")
    if "/" in leaf:
        tag, sub = leaf.split("/", 1)
        return tag, sub
    return leaf, None


class ConfirmSession:
    def __init__(self, store: Store, tax: TagTaxonomy, top: int = 100,
                 user: str | None = None) -> None:
        self.store = store
        self.tax = tax
        self.top = top
        self.user = user or getpass.getuser()

    # --- queue ----------------------------------------------------------
    def build_queue(self) -> list[QueueItem]:
        profiles = top_senders(self.store, self.top)
        rules = {(r.scope, r.key): r for r in self.store.get_rules()}
        defs = {(d.scope, d.key): d for d in self.store.get_deferrals()}
        items = self._domain_items(profiles, rules, defs)
        items += [self._item(p.from_addr, "addr", p.from_domain, p.message_count,
                             p.keyword_hint, p.example_subjects, rules, defs)
                  for p in profiles]
        # Undecided first (highest count), then deferred, then decided.
        order = {"undecided": 0, "stale": 0, "deferred": 1, "decided": 2}
        return sorted(items, key=lambda i: (order[i.status], -i.message_count))

    def _domain_items(self, profiles, rules, defs) -> list[QueueItem]:
        counts: dict[str, int] = {}
        for p in profiles:
            counts[p.from_domain] = counts.get(p.from_domain, 0) + p.message_count
        out = []
        for domain, count in counts.items():
            if not domain:
                continue
            out.append(self._item(domain, "domain", domain, count, None, (),
                                  rules, defs))
        return out

    def _item(self, key, scope, label, count, hint, subjects, rules, defs) -> QueueItem:
        rule = rules.get((scope, key))
        defr = defs.get((scope, key))
        if rule is not None:
            status: Status = "decided"
            leaf = rule.leaf
        elif defr is not None:
            status, leaf = "deferred", None
        else:
            status, leaf = "undecided", None
        return QueueItem(key, scope, label, count, hint, subjects, status, leaf,
                         defr.note if defr else "")

    # --- actions (per-decision writes) ---------------------------------
    def accept(self, item: QueueItem) -> None:
        if not item.hint:
            raise LeafError("no hint to accept; override explicitly")
        self.set_rule(item.key, item.scope, item.hint)

    def set_rule(self, key: str, scope: str, leaf: str) -> None:
        tag, sub = parse_leaf(leaf, self.tax)
        self.store.upsert_rule(SenderRule(
            key=key, scope=scope, tag=tag, subtag=sub,
            confirmed_by=self.user, confirmed_at=datetime.now()))

    def defer(self, key: str, scope: str, note: str = "") -> None:
        self.store.upsert_deferral(Deferral(key=key, scope=scope, note=note))

    # --- projection -----------------------------------------------------
    def coverage(self) -> Coverage:
        resolver = Resolver(self.store.get_rules(), self.tax)
        total = covered = 0
        for msg in self.store.iter_messages():
            total += 1
            if resolver.resolve(msg) is not None:
                covered += 1
        return Coverage(total=total, covered=covered)
