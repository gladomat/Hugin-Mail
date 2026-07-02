"""Load, hash, render, and budget-check the versioned tag taxonomy (§7, §9.1)."""

from __future__ import annotations

import hashlib
from importlib import resources
from pathlib import Path

import yaml

from .models import KeywordRule, TagNode, TagTaxonomy
from .tokens import estimate_tokens

# Budget for `system prompt + taxonomy` rendered form (§9.1).
TAXONOMY_TOKEN_BUDGET = 1200


class TaxonomyBudgetError(ValueError):
    """Raised when the rendered taxonomy exceeds its token allowance."""


def _hash_payload(version: str, tags: list[dict], rules: list[dict]) -> str:
    canonical = yaml.safe_dump(
        {"version": version, "tags": tags, "keyword_rules": rules},
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def load_taxonomy(version: str = "v1", path: Path | None = None) -> TagTaxonomy:
    if path is not None:
        raw = yaml.safe_load(path.read_text())
    else:
        data = resources.files("huginmail.taxonomies").joinpath(f"{version}.yaml")
        raw = yaml.safe_load(data.read_text())

    tags = tuple(
        TagNode(
            name=t["name"],
            definition=t["definition"],
            subtags=tuple(t.get("subtags", [])),
        )
        for t in raw["tags"]
    )
    rules = tuple(
        KeywordRule(
            tag=r["tag"],
            keywords=tuple(k.lower() for k in r["keywords"]),
            fields=tuple(r.get("fields", ["subject"])),
        )
        for r in raw.get("keyword_rules", [])
    )
    content_hash = _hash_payload(
        raw["version"], raw["tags"], raw.get("keyword_rules", [])
    )
    return TagTaxonomy(
        version=raw["version"],
        tags=tags,
        keyword_rules=rules,
        changelog=raw.get("changelog", ""),
        content_hash=content_hash,
    )


def render_prompt(tax: TagTaxonomy) -> str:
    """Compressed one-liner-per-tag form for the LLM prompt (not full YAML)."""
    lines = [f"Taxonomy {tax.version}:"]
    for t in tax.tags:
        sub = f" (subtags: {', '.join(t.subtags)})" if t.subtags else ""
        lines.append(f"- {t.name}: {t.definition}{sub}")
    return "\n".join(lines)


def check_budget(tax: TagTaxonomy, budget: int = TAXONOMY_TOKEN_BUDGET) -> int:
    """Return rendered token count; raise if over budget. Used as a CI-style gate."""
    count = estimate_tokens(render_prompt(tax))
    if count > budget:
        raise TaxonomyBudgetError(
            f"Taxonomy {tax.version} renders to {count} tokens, over budget {budget}"
        )
    return count
