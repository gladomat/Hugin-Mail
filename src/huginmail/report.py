"""Pass 1: sender aggregation (Polars) + top-N sender Markdown report."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .models import SenderProfile
from .store import Store


def _messages_frame(store: Store) -> pl.DataFrame:
    rows = store._conn.execute(
        """SELECT from_addr, from_domain, subject, date, keyword_hint
           FROM messages"""
    ).fetchall()
    return pl.DataFrame(
        {
            "from_addr": [r["from_addr"] for r in rows],
            "from_domain": [r["from_domain"] for r in rows],
            "subject": [r["subject"] for r in rows],
            "date": [r["date"] for r in rows],
            "keyword_hint": [r["keyword_hint"] for r in rows],
        },
        schema={
            "from_addr": pl.Utf8, "from_domain": pl.Utf8, "subject": pl.Utf8,
            "date": pl.Utf8, "keyword_hint": pl.Utf8,
        },
    )


def _dominant_hint(hints: pl.Series) -> str | None:
    non_null = [h for h in hints.to_list() if h]
    if not non_null:
        return None
    return max(set(non_null), key=non_null.count)


def _aggregate(store: Store) -> list[SenderProfile]:
    """All senders, aggregated and sorted by descending message count."""
    df = _messages_frame(store)
    if df.height == 0:
        return []
    grouped = (
        df.group_by("from_addr")
        .agg(
            pl.col("from_domain").first(),
            pl.len().alias("message_count"),
            pl.col("date").min().alias("first_seen"),
            pl.col("date").max().alias("last_seen"),
            pl.col("keyword_hint"),
            pl.col("subject").head(3).alias("example_subjects"),
        )
        .sort("message_count", descending=True)
    )
    return [
        SenderProfile(
            from_addr=row["from_addr"],
            from_domain=row["from_domain"] or "",
            message_count=row["message_count"],
            first_seen=None,
            last_seen=None,
            keyword_hint=_dominant_hint(pl.Series(row["keyword_hint"])),
            example_subjects=tuple(s for s in row["example_subjects"] if s),
        )
        for row in grouped.iter_rows(named=True)
    ]


def top_senders(store: Store, top: int = 100) -> list[SenderProfile]:
    return _aggregate(store)[:top]


def senders_matching(store: Store, substr: str) -> list[SenderProfile]:
    """Senders whose address or domain contains `substr` (case-insensitive),
    at any rank — used by `confirm --sender` to reach the long tail."""
    s = substr.lower()
    return [p for p in _aggregate(store)
            if s in p.from_addr.lower() or s in p.from_domain.lower()]


def render_markdown(profiles: list[SenderProfile], taxonomy_version: str, top: int) -> str:
    lines = [
        f"# Top {top} senders",
        "",
        f"_Taxonomy version: {taxonomy_version}_",
        "",
        "| # | Sender | Domain | Count | Hint | Example subjects |",
        "|---|--------|--------|-------|------|------------------|",
    ]
    for i, p in enumerate(profiles, 1):
        subjects = " · ".join(s.replace("|", "\\|") for s in p.example_subjects[:3])
        lines.append(
            f"| {i} | {p.from_addr} | {p.from_domain} | {p.message_count} | "
            f"{p.keyword_hint or '—'} | {subjects} |"
        )
    return "\n".join(lines) + "\n"


def write_sender_report(
    store: Store, out_dir: Path, taxonomy_version: str, top: int = 100
) -> Path:
    profiles = top_senders(store, top)
    md = render_markdown(profiles, taxonomy_version, top)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"senders_top{top}.md"
    path.write_text(md)
    return path
