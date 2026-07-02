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


def classify_rules(store: Store, tax: TagTaxonomy) -> ClassifyResult:
    resolver = Resolver(store.get_rules(), tax)
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
    limit: int | None = None,
) -> BatchResult:
    """Classify rule-uncovered messages via the LLM (K=1 one-shot per message),
    writing method='llm' records with confidence, rationale, and provenance."""
    resolver = Resolver(store.get_rules(), tax)
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
        if out.tag == "unclassified":
            res.unclassified += 1
        store.add_classification(ClassificationRecord(
            uid=msg.uid, folder=msg.folder, tag=out.tag,
            subtags=(out.subtag,) if out.subtag else (),
            confidence=out.confidence, method="llm",
            taxonomy_version=tax.version, taxonomy_hash=tax.content_hash,
            model_id=out.model_id, prompt_version=out.prompt_version,
            rationale=out.rationale, truncated=out.truncated, created_at=now,
        ))
    return res
