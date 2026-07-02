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
