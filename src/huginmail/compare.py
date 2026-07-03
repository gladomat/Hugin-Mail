"""Model comparison (dry-run): classify a fixed sample under several models
without persisting, so model choice can be judged on quality, not guesswork.
Never writes ClassificationRecords."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from typing import Callable

from .config import LlmConfig
from .llm import LlmClient, LlmOutcome, OpenAiClient, classify_message
from .models import EmailMessage, TagTaxonomy
from .store import Store

ClientFactory = Callable[[LlmConfig], LlmClient]


@dataclass
class ModelRun:
    model_id: str
    outcomes: dict[int, LlmOutcome] = field(default_factory=dict)  # keyed by uid
    elapsed: float = 0.0


@dataclass
class Comparison:
    sample: list[EmailMessage]
    runs: list[ModelRun]

    @property
    def agreement(self) -> float:
        """Fraction of the sample where every model produced the same tag."""
        if not self.sample or len(self.runs) < 2:
            return 1.0
        agree = 0
        for msg in self.sample:
            tags = {r.outcomes[msg.uid].tag for r in self.runs if msg.uid in r.outcomes}
            if len(tags) == 1:
                agree += 1
        return agree / len(self.sample)


def _classify_all(client: LlmClient, tax: TagTaxonomy, sample: list[EmailMessage],
                  cfg: LlmConfig, concurrency: int) -> dict[int, LlmOutcome]:
    if concurrency <= 1:
        return {m.uid: classify_message(client, tax, m, cfg) for m in sample}
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = {m.uid: ex.submit(classify_message, client, tax, m, cfg) for m in sample}
    return {uid: f.result() for uid, f in futs.items()}


def compare_models(
    store: Store, tax: TagTaxonomy, base: LlmConfig, model_ids: list[str],
    n: int, client_factory: ClientFactory = OpenAiClient, concurrency: int = 1,
) -> Comparison:
    sample = list(islice(store.iter_messages(), n))
    runs: list[ModelRun] = []
    for mid in model_ids:
        cfg = base.model_copy(update={"model_id": mid})
        client = client_factory(cfg)
        t0 = time.perf_counter()
        outcomes = _classify_all(client, tax, sample, cfg, concurrency)
        runs.append(ModelRun(mid, outcomes, time.perf_counter() - t0))
    return Comparison(sample, runs)


def render_comparison(cmp: Comparison) -> str:
    ids = [r.model_id for r in cmp.runs]
    lines = [
        "# Model comparison",
        "",
        f"_Sample: {len(cmp.sample)} messages · agreement: "
        f"{cmp.agreement * 100:.0f}%_",
        "",
        "## Timing",
    ]
    n = max(len(cmp.sample), 1)
    for r in cmp.runs:
        lines.append(f"- {r.model_id}: {r.elapsed:.1f}s total, "
                     f"{r.elapsed / n:.2f}s/msg")
    lines += ["", "## Per-message", ""]
    header = "| subject | " + " | ".join(ids) + " | agree |"
    lines.append(header)
    lines.append("|" + "---|" * (len(ids) + 2))
    for msg in cmp.sample:
        cells = []
        tags = set()
        for r in cmp.runs:
            o = r.outcomes.get(msg.uid)
            if o is None:
                cells.append("—")
                continue
            tags.add(o.tag)
            cells.append(f"{o.tag} ({o.confidence:.2f}) {o.rationale}".replace("|", "/"))
        agree = "✓" if len(tags) == 1 else "✗"
        subj = (msg.subject or "")[:40].replace("|", "/")
        lines.append(f"| {subj} | " + " | ".join(cells) + f" | {agree} |")
    return "\n".join(lines) + "\n"


def write_comparison(cmp: Comparison, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "compare.md"
    path.write_text(render_comparison(cmp))
    return path
