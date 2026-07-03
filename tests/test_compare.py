from __future__ import annotations

from huginmail.compare import compare_models, render_comparison
from huginmail.config import LlmConfig
from huginmail.sync import sync_folder
from conftest import FakeImapSource, raw


class ByModelClient:
    """Returns a canned reply keyed by the config's model_id."""
    def __init__(self, cfg: LlmConfig):
        self.model = cfg.model_id

    def complete(self, system, user, sampling):
        tag = "junk" if self.model == "small" else "newsletter"
        return f'{{"tag":"{tag}","confidence":0.9,"rationale":"r"}}'


def _seed(store, tax, n=5):
    msgs = [raw(i, f"m{i}", subject=f"thing {i}", from_addr=f"u{i}@z.com")
            for i in range(1, n + 1)]
    sync_folder(store, FakeImapSource({"INBOX": (10, msgs)}), tax, "INBOX")


def test_compare_runs_all_models(store, tax):
    _seed(store, tax, 4)
    cmp = compare_models(store, tax, LlmConfig(), ["small", "big"], n=4,
                         client_factory=ByModelClient)
    assert len(cmp.sample) == 4 and len(cmp.runs) == 2
    assert {r.model_id for r in cmp.runs} == {"small", "big"}
    assert all(len(r.outcomes) == 4 for r in cmp.runs)


def test_no_persist(store, tax):
    _seed(store, tax, 3)
    compare_models(store, tax, LlmConfig(), ["small", "big"], n=3,
                   client_factory=ByModelClient)
    assert store.classification_count() == 0  # dry-run: nothing written


def test_agreement_zero_when_models_differ(store, tax):
    _seed(store, tax, 4)
    cmp = compare_models(store, tax, LlmConfig(), ["small", "big"], n=4,
                         client_factory=ByModelClient)
    assert cmp.agreement == 0.0  # small→junk, big→newsletter, never agree


def test_agreement_full_when_same_model_twice(store, tax):
    _seed(store, tax, 4)
    cmp = compare_models(store, tax, LlmConfig(), ["small", "small"], n=4,
                         client_factory=ByModelClient)
    assert cmp.agreement == 1.0


def test_sample_capped(store, tax):
    _seed(store, tax, 10)
    cmp = compare_models(store, tax, LlmConfig(), ["small", "big"], n=3,
                         client_factory=ByModelClient)
    assert len(cmp.sample) == 3


def test_render_has_table_and_agreement(store, tax):
    _seed(store, tax, 2)
    cmp = compare_models(store, tax, LlmConfig(), ["small", "big"], n=2,
                         client_factory=ByModelClient)
    md = render_comparison(cmp)
    assert "Model comparison" in md and "agree" in md
    assert "small" in md and "big" in md
