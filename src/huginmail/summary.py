"""SUMMARY.md — the standing inbox overview, regenerated after classify/export
(§8). One screen: coverage, tag distribution, method breakdown, top senders per
tag, and the versions everything was produced under."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .export import manifest_frame
from .store import Store
from .taxonomy import TagTaxonomy


def _distribution(df: pl.DataFrame, col: str) -> list[tuple[str, int]]:
    if df.height == 0:
        return []
    g = df.group_by(col).agg(pl.len().alias("n")).sort("n", descending=True)
    return [(r[col], r["n"]) for r in g.iter_rows(named=True)]


def _top_senders_per_tag(df: pl.DataFrame, k: int = 10) -> dict[str, list[tuple[str, int]]]:
    out: dict[str, list[tuple[str, int]]] = {}
    if df.height == 0:
        return out
    for tag in df["tag"].unique().to_list():
        sub = df.filter(pl.col("tag") == tag)
        g = (sub.group_by("from_addr").agg(pl.len().alias("n"))
             .sort("n", descending=True).head(k))
        out[tag] = [(r["from_addr"], r["n"]) for r in g.iter_rows(named=True)]
    return out


def render_summary(store: Store, tax: TagTaxonomy) -> str:
    df = manifest_frame(store, tax)
    distinct = store.distinct_message_count()
    classified = df.height
    unclassified = max(distinct - classified, 0)
    pct = (classified / distinct * 100) if distinct else 0.0

    lines = [
        "# Inbox summary",
        "",
        f"_Taxonomy {tax.version} ({tax.content_hash})_",
        "",
        "## Coverage",
        f"- Distinct messages: {distinct}",
        f"- Classified: {classified} ({pct:.1f}%)",
        f"- Unclassified: {unclassified}",
        "",
        "## Tag distribution",
    ]
    for tag, n in _distribution(df, "tag"):
        lines.append(f"- {tag}: {n}")
    lines += ["", "## Method breakdown (rule leverage)"]
    for method, n in _distribution(df, "method"):
        share = (n / classified * 100) if classified else 0.0
        lines.append(f"- {method}: {n} ({share:.1f}%)")
    lines += ["", "## Top senders per tag"]
    for tag, senders in _top_senders_per_tag(df).items():
        lines.append(f"### {tag}")
        for addr, n in senders:
            lines.append(f"- {addr}: {n}")
    lines += ["", "## Needs review (lowest-confidence LLM calls)"]
    for addr, subject, tag, conf in _lowest_confidence(df):
        lines.append(f"- [{conf:.2f}] {tag} — {addr}: {subject[:60]}")
    if unclassified:
        lines.append(f"- …plus {unclassified} unclassified message(s) to triage")
    return "\n".join(lines) + "\n"


def _lowest_confidence(df: pl.DataFrame, k: int = 15) -> list[tuple[str, str, str, float]]:
    """The k least-confident LLM classifications — review worst-first."""
    if df.height == 0 or "method" not in df.columns:
        return []
    llm = df.filter(pl.col("method") == "llm").sort("confidence").head(k)
    return [(r["from_addr"], r["subject"] or "", r["tag"], r["confidence"])
            for r in llm.iter_rows(named=True)]


def write_summary(store: Store, tax: TagTaxonomy, data_dir: Path) -> Path:
    path = data_dir / "SUMMARY.md"
    path.write_text(render_summary(store, tax))
    return path
