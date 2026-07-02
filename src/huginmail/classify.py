"""Pass 4 (rules path): apply the resolver over the index, writing append-only
ClassificationRecords for rule-covered messages. LLM classification of the
residue is added by S6b/S8. Idempotent: a message whose latest tag already
matches is not re-written."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .config import LlmConfig
from .llm import LlmClient, classify_message
from .models import ClassificationRecord, TagTaxonomy
from .rules import Resolver
from .store import Store


@dataclass
class ClassifyResult:
    scanned: int = 0
    written: int = 0
    unchanged: int = 0
    uncovered: int = 0  # left for the LLM pass


def classify_rules(store: Store, tax: TagTaxonomy,
                   keyword_authoritative: bool = True) -> ClassifyResult:
    resolver = Resolver(store.get_rules(), tax, keyword_authoritative)
    for r in resolver.invalid:
        store.mark_rule_stale(r.scope, r.key)

    res = ClassifyResult()
    now = datetime.now()
    for msg in store.iter_messages():
        res.scanned += 1
        resolved = resolver.resolve(msg)
        if resolved is None:
            res.uncovered += 1
            continue
        if store.latest_tag(msg.folder, msg.uid, tax.content_hash) == _leaf(resolved):
            res.unchanged += 1
            continue
        store.add_classification(ClassificationRecord(
            uid=msg.uid, folder=msg.folder, tag=resolved.tag,
            subtags=(resolved.subtag,) if resolved.subtag else (),
            confidence=resolved.confidence, method=resolved.method,
            taxonomy_version=tax.version, taxonomy_hash=tax.content_hash,
            created_at=now,
        ))
        res.written += 1
    return res


def _leaf(resolved) -> str:
    return resolved.tag


@dataclass
class BatchResult:
    called: int = 0
    unclassified: int = 0


def classify_llm_batch(
    store: Store, tax: TagTaxonomy, client: LlmClient, cfg: LlmConfig,
    limit: int | None = None, keyword_authoritative: bool = True,
    confidence_threshold: float = 0.0,
) -> BatchResult:
    """Classify rule-uncovered messages via the LLM (K=1 one-shot per message),
    writing method='llm' records with confidence, rationale, and provenance.

    A message whose LLM confidence is below `confidence_threshold` is recorded as
    `unclassified` (abstention over a guess, §8) — its rationale/confidence are
    kept so it can be reviewed."""
    resolver = Resolver(store.get_rules(), tax, keyword_authoritative)
    res = BatchResult()
    now = datetime.now()
    for msg in store.iter_messages():
        if limit is not None and res.called >= limit:
            break
        if resolver.resolve(msg) is not None:
            continue  # covered by a rule; skip
        if store.latest_tag(msg.folder, msg.uid, tax.content_hash) is not None:
            continue  # already has a classification for this taxonomy
        out = classify_message(client, tax, msg, cfg)
        res.called += 1
        tag, subtag = out.tag, out.subtag
        if tag != "unclassified" and out.confidence < confidence_threshold:
            tag, subtag = "unclassified", None  # abstain: too uncertain
        if tag == "unclassified":
            res.unclassified += 1
        store.add_classification(ClassificationRecord(
            uid=msg.uid, folder=msg.folder, tag=tag,
            subtags=(subtag,) if subtag else (),
            confidence=out.confidence, method="llm",
            taxonomy_version=tax.version, taxonomy_hash=tax.content_hash,
            model_id=out.model_id, prompt_version=out.prompt_version,
            rationale=out.rationale, truncated=out.truncated, created_at=now,
        ))
    return res
