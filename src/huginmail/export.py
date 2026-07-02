"""Manifest export: Parquet (canonical) + CSV twin (convenience view, §10)."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .store import Store
from .taxonomy import TagTaxonomy

_COLS = [
    "folder", "uid", "message_id", "from_addr", "from_domain", "subject", "date",
    "tag", "subtags", "confidence", "method", "taxonomy_version", "model_id",
    "prompt_version", "rationale", "truncated", "created_at",
]


def manifest_frame(store: Store, tax: TagTaxonomy) -> pl.DataFrame:
    rows = store.manifest_rows(tax.content_hash)
    data = {c: [r[c] for r in rows] for c in _COLS}
    return pl.DataFrame(data) if rows else pl.DataFrame({c: [] for c in _COLS})


def export_manifest(store: Store, tax: TagTaxonomy, out_dir: Path) -> tuple[Path, Path]:
    """Write manifest.parquet + manifest.csv (same basename). Returns both paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    df = manifest_frame(store, tax)
    parquet = out_dir / "manifest.parquet"
    csv = out_dir / "manifest.csv"
    df.write_parquet(parquet)
    df.write_csv(csv)
    return parquet, csv


def render_sieve(rules) -> str:
    """Confirmed sender/domain rules as Sieve fileinto rules. v1 produces them;
    it never installs them (read-only)."""
    lines = ['require ["fileinto"];', ""]
    for r in sorted(rules, key=lambda x: (x.scope, x.key)):
        test = (f'address :domain :is "from" "{r.key}"' if r.scope == "domain"
                else f'address :is "from" "{r.key}"')
        lines.append(f'if {test} {{ fileinto "{r.leaf}"; }}')
    return "\n".join(lines) + "\n"


def render_rules_text(rules) -> str:
    """Provider-agnostic sender→tag mapping (scope,key,leaf)."""
    lines = ["scope\tkey\tleaf"]
    for r in sorted(rules, key=lambda x: (x.scope, x.key)):
        lines.append(f"{r.scope}\t{r.key}\t{r.leaf}")
    return "\n".join(lines) + "\n"


def export_rules(store: Store, out_dir: Path, fmt: str = "text") -> Path:
    """Export the proposed sender→tag rules. fmt: 'text' (default) or 'sieve'."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rules = store.get_rules()
    if fmt == "sieve":
        path = out_dir / "rules.sieve"
        path.write_text(render_sieve(rules))
    else:
        path = out_dir / "rules.tsv"
        path.write_text(render_rules_text(rules))
    return path
