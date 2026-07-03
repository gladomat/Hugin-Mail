"""Per-message review — the correction half of the LLM-first workflow. Walk the
LLM's classifications (worst-first) and retag individual messages. A retag writes
an append-only method='human' record that wins over the LLM's (latest-wins).
UI-free so it is unit-testable; review_tui.py is a thin driver."""

from __future__ import annotations

import getpass
from dataclasses import dataclass
from datetime import datetime

from .confirm import parse_leaf  # shared taxonomy-leaf validation
from .models import ClassificationRecord, SenderRule, TagTaxonomy
from .store import Store


@dataclass
class ReviewItem:
    folder: str
    uid: int
    subject: str
    snippet: str
    tag: str
    confidence: float
    rationale: str
    from_addr: str = ""


class ReviewSession:
    def __init__(self, store: Store, tax: TagTaxonomy, min_conf: float = 0.0,
                 max_conf: float = 1.0, tag: str | None = None,
                 user: str | None = None) -> None:
        self.store = store
        self.tax = tax
        self.min_conf = min_conf
        self.max_conf = max_conf
        self.tag = tag
        self.user = user or getpass.getuser()

    def candidates(self) -> list[ReviewItem]:
        rows = self.store.review_candidates(
            self.tax.content_hash, self.min_conf, self.max_conf, self.tag)
        return [
            ReviewItem(folder=r["folder"], uid=r["uid"], subject=r["subject"] or "",
                       snippet=r["snippet"] or "", tag=r["tag"],
                       confidence=r["confidence"], rationale=r["rationale"] or "",
                       from_addr=r["from_addr"] or "")
            for r in rows
        ]

    def retag(self, item: ReviewItem, leaf: str) -> None:
        """Write a human classification that overrides the LLM's for this message."""
        tag, subtag = parse_leaf(leaf, self.tax)  # raises LeafError if invalid
        self.store.add_classification(ClassificationRecord(
            uid=item.uid, folder=item.folder, tag=tag,
            subtags=(subtag,) if subtag else (), confidence=1.0, method="human",
            taxonomy_version=self.tax.version, taxonomy_hash=self.tax.content_hash,
            rationale="human review", created_at=datetime.now()))

    def make_sender_rule(self, from_addr: str, leaf: str) -> None:
        """Optional: promote a correction to a sender rule (covers future mail)."""
        tag, subtag = parse_leaf(leaf, self.tax)
        self.store.upsert_rule(SenderRule(
            key=from_addr.lower(), scope="addr", tag=tag, subtag=subtag,
            confirmed_by=self.user, confirmed_at=datetime.now()))
