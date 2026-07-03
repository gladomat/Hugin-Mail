"""Model comparison across *separate* runs — for hardware that can't hold two
models at once. Each `compare` run classifies a fixed sample under the currently
loaded model and saves the result to disk; once two or more runs exist they are
diffed. Reload the server with the next model between runs. Never persists
ClassificationRecords."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from typing import Callable

from .config import LlmConfig
from .llm import LlmClient, OpenAiClient, classify_message
from .models import EmailMessage, TagTaxonomy
from .store import Store

ClientFactory = Callable[[LlmConfig], LlmClient]


@dataclass
class Run:
    model_id: str
    elapsed: float
    sample: list[tuple[int, str, str]]        # (uid, folder, subject) — the fixed set
    outcomes: dict[int, dict]                 # uid -> {tag, subtag, confidence, rationale}

    def to_json(self) -> dict:
        return {"model_id": self.model_id, "elapsed": self.elapsed,
                "sample": self.sample,
                "outcomes": {str(k): v for k, v in self.outcomes.items()}}

    @classmethod
    def from_json(cls, d: dict) -> "Run":
        return cls(d["model_id"], d["elapsed"],
                   [tuple(x) for x in d["sample"]],
                   {int(k): v for k, v in d["outcomes"].items()})


def _sanitize(model_id: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in model_id)


def runs_dir(reports_dir: Path) -> Path:
    return reports_dir / "compare_runs"


def load_runs(reports_dir: Path) -> list[Run]:
    d = runs_dir(reports_dir)
    if not d.exists():
        return []
    return [Run.from_json(json.loads(p.read_text())) for p in sorted(d.glob("*.json"))]


def save_run(run: Run, reports_dir: Path) -> Path:
    d = runs_dir(reports_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{_sanitize(run.model_id)}.json"
    path.write_text(json.dumps(run.to_json(), indent=2))
    return path


def reset_runs(reports_dir: Path) -> int:
    d = runs_dir(reports_dir)
    if not d.exists():
        return 0
    files = list(d.glob("*.json"))
    for p in files:
        p.unlink()
    return len(files)


def _pick_sample(store: Store, n: int, prior: list[Run]) -> list[EmailMessage]:
    """Reuse the sample from a prior run if present (guarantees alignment even if
    the index changed); otherwise the first N messages, deterministically."""
    if prior:
        wanted = {uid for uid, _, _ in prior[0].sample}
        return [m for m in store.iter_messages() if m.uid in wanted]
    return list(islice(store.iter_messages(), n))


def run_model(
    store: Store, tax: TagTaxonomy, base: LlmConfig, model_id: str, n: int,
    reports_dir: Path, client_factory: ClientFactory = OpenAiClient,
    concurrency: int = 1,
) -> Run:
    prior = load_runs(reports_dir)
    sample = _pick_sample(store, n, prior)
    cfg = base.model_copy(update={"model_id": model_id})
    client = client_factory(cfg)

    t0 = time.perf_counter()
    outcomes = _classify_all(client, tax, sample, cfg, concurrency)
    elapsed = time.perf_counter() - t0

    run = Run(model_id, elapsed,
              [(m.uid, m.folder, m.subject or "") for m in sample],
              {uid: {"tag": o.tag, "subtag": o.subtag, "confidence": o.confidence,
                     "rationale": o.rationale} for uid, o in outcomes.items()})
    save_run(run, reports_dir)
    return run


def _classify_all(client, tax, sample, cfg, concurrency):
    if concurrency <= 1:
        return {m.uid: classify_message(client, tax, m, cfg) for m in sample}
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = {m.uid: ex.submit(classify_message, client, tax, m, cfg) for m in sample}
    return {uid: f.result() for uid, f in futs.items()}


def agreement(runs: list[Run]) -> float:
    if len(runs) < 2:
        return 1.0
    sample = runs[0].sample
    if not sample:
        return 1.0
    agree = sum(1 for uid, _, _ in sample
                if len({r.outcomes.get(uid, {}).get("tag") for r in runs}) == 1)
    return agree / len(sample)


def render_diff(runs: list[Run]) -> str:
    ids = [r.model_id for r in runs]
    lines = [
        "# Model comparison",
        "",
        f"_Sample: {len(runs[0].sample) if runs else 0} messages · "
        f"agreement: {agreement(runs) * 100:.0f}%_",
        "",
        "## Timing",
    ]
    for r in runs:
        n = max(len(r.sample), 1)
        lines.append(f"- {r.model_id}: {r.elapsed:.1f}s total, {r.elapsed / n:.2f}s/msg")
    lines += ["", "## Per-message (disagreements first)", ""]
    lines.append("| subject | " + " | ".join(ids) + " | agree |")
    lines.append("|" + "---|" * (len(ids) + 2))
    sample = runs[0].sample if runs else []

    def row(uid, folder, subject):
        cells, tags = [], set()
        for r in runs:
            o = r.outcomes.get(uid)
            if o is None:
                cells.append("—")
                continue
            tags.add(o["tag"])
            cells.append(f"{o['tag']} ({o['confidence']:.2f}) {o['rationale']}"
                         .replace("|", "/"))
        agree = len(tags) == 1
        subj = (subject or "")[:40].replace("|", "/")
        return agree, f"| {subj} | " + " | ".join(cells) + f" | {'✓' if agree else '✗'} |"

    rows = [row(uid, f, s) for uid, f, s in sample]
    for _, line in sorted(rows, key=lambda x: x[0]):  # disagreements (False) first
        lines.append(line)
    return "\n".join(lines) + "\n"


def write_diff(runs: list[Run], reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "compare.md"
    path.write_text(render_diff(runs))
    return path
