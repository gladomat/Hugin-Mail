from __future__ import annotations

from huginmail.compare import (
    agreement,
    load_runs,
    render_diff,
    reset_runs,
    run_model,
)
from huginmail.config import LlmConfig
from huginmail.sync import sync_folder
from conftest import FakeImapSource, raw


class ByModelClient:
    """Canned reply keyed by the config's model_id."""
    def __init__(self, cfg: LlmConfig):
        self.model = cfg.model_id

    def complete(self, system, user, sampling):
        tag = "junk" if self.model == "small" else "newsletter"
        return f'{{"tag":"{tag}","confidence":0.9,"rationale":"r"}}'


def _seed(store, tax, n=5):
    msgs = [raw(i, f"m{i}", subject=f"thing {i}", from_addr=f"u{i}@z.com")
            for i in range(1, n + 1)]
    sync_folder(store, FakeImapSource({"INBOX": (10, msgs)}), tax, "INBOX")


def test_single_run_saves_and_no_persist(store, tax, tmp_path):
    _seed(store, tax, 4)
    run_model(store, tax, LlmConfig(), "small", 4, tmp_path,
              client_factory=ByModelClient)
    runs = load_runs(tmp_path)
    assert len(runs) == 1 and runs[0].model_id == "small"
    assert store.classification_count() == 0  # dry-run


def test_two_runs_align_on_same_sample(store, tax, tmp_path):
    _seed(store, tax, 6)
    run_model(store, tax, LlmConfig(), "small", 3, tmp_path,
              client_factory=ByModelClient)
    # second run reuses the first run's sample even with a larger --sample
    run_model(store, tax, LlmConfig(), "big", 99, tmp_path,
              client_factory=ByModelClient)
    runs = load_runs(tmp_path)
    assert len(runs) == 2
    assert {u for u, _, _ in runs[0].sample} == {u for u, _, _ in runs[1].sample}


def test_agreement_zero_when_models_differ(store, tax, tmp_path):
    _seed(store, tax, 4)
    run_model(store, tax, LlmConfig(), "small", 4, tmp_path,
              client_factory=ByModelClient)
    run_model(store, tax, LlmConfig(), "big", 4, tmp_path,
              client_factory=ByModelClient)
    assert agreement(load_runs(tmp_path)) == 0.0


def test_render_disagreements_and_reset(store, tax, tmp_path):
    _seed(store, tax, 3)
    run_model(store, tax, LlmConfig(), "small", 3, tmp_path,
              client_factory=ByModelClient)
    run_model(store, tax, LlmConfig(), "big", 3, tmp_path,
              client_factory=ByModelClient)
    md = render_diff(load_runs(tmp_path))
    assert "Model comparison" in md and "small" in md and "big" in md
    assert reset_runs(tmp_path) == 2 and load_runs(tmp_path) == []
