from __future__ import annotations

from datetime import datetime

import pytest
from typer.testing import CliRunner

from huginmail.config import Config, ImapConfig, OrganizeConfig
from huginmail.models import ClassificationRecord
from huginmail.organize import dest_for, plan_actions
from huginmail.store import Store
from huginmail.sync import sync_folder
from huginmail.taxonomy import load_taxonomy
from conftest import FakeImapSource, raw

runner = CliRunner()


def _classify(store, tax, uid, tag, subtags=(), method="llm", folder="INBOX",
              when="2026-01-01T00:00:00"):
    store.add_classification(ClassificationRecord(
        uid=uid, folder=folder, tag=tag, subtags=tuple(subtags), confidence=1.0,
        method=method, taxonomy_version=tax.version, taxonomy_hash=tax.content_hash,
        created_at=datetime.fromisoformat(when)))


def _seed(store, tax, uidvalidity=42):
    msgs = [raw(1, "m1", subject="Weekly digest", from_addr="news@z.com"),
            raw(2, "m2", subject="Payment received", from_addr="bank@z.com"),
            raw(3, "m3", subject="hi", from_addr="bob@z.com"),
            raw(4, "m4", subject="BUY NOW", from_addr="spam@z.com"),
            raw(5, "m5", subject="unsure", from_addr="x@z.com")]
    sync_folder(store, FakeImapSource({"INBOX": (uidvalidity, msgs)}), tax, "INBOX")
    _classify(store, tax, 1, "newsletter")
    _classify(store, tax, 2, "receipt", ["bank"])
    _classify(store, tax, 3, "keep")
    _classify(store, tax, 4, "junk", ["marketing"])
    _classify(store, tax, 5, "unclassified")


# --- unit: leaf → destination ------------------------------------------------
def test_dest_for_defaults():
    cfg = OrganizeConfig()
    assert dest_for("newsletter", cfg) == "Newsletter"
    assert dest_for("receipt/bank", cfg) == "Receipt/Bank"
    assert dest_for("junk", cfg) == "Junk"
    assert dest_for("junk/marketing", cfg) == "Junk/Marketing"
    assert dest_for("keep", cfg) is None
    assert dest_for("unclassified", cfg) is None


def test_dest_for_overrides():
    cfg = OrganizeConfig(map={"newsletter": "Lists/News", "receipt": "Finance"},
                         junk_folder="Spam")
    assert dest_for("newsletter", cfg) == "Lists/News"
    assert dest_for("receipt/bank", cfg) == "Finance/Bank"   # tag map + subtag
    assert dest_for("junk", cfg) == "Spam"


# --- plan --------------------------------------------------------------------
def test_plan_skips_keep_and_unclassified(store, tax):
    _seed(store, tax)
    actions = plan_actions(store, tax, OrganizeConfig())
    dests = {a.uid: a.dest for a in actions}
    assert dests == {1: "Newsletter", 2: "Receipt/Bank", 4: "Junk/Marketing"}


def test_plan_respects_human_latest_wins(store, tax):
    _seed(store, tax)
    # human retag of the newsletter to keep → should drop out of the plan
    _classify(store, tax, 1, "keep", method="human", when="2026-02-01T00:00:00")
    uids = {a.uid for a in plan_actions(store, tax, OrganizeConfig())}
    assert 1 not in uids


# --- CLI apply path (fake write source) -------------------------------------
class FakeWriteSource:
    def __init__(self, *_a, uidvalidity=42, present=(1, 2, 4)):
        self._uidvalidity = uidvalidity
        self._present = set(present)
        self.created: list[str] = []
        self.applied: list[tuple[list[int], str, str]] = []

    def select(self, folder):
        return self._uidvalidity

    def existing_uids(self, folder):
        return set(self._present)

    def ensure_folder(self, name):
        self.created.append(name)

    def apply(self, uids, dest, mechanism):
        self.applied.append((list(uids), dest, mechanism))

    def close(self):
        pass


def _cfg(tmp_path):
    return Config(data_dir=tmp_path, imap=ImapConfig(host="h", username="u"))


def _prime_cli(monkeypatch, tmp_path, fake, uidvalidity=42):
    cfg = _cfg(tmp_path)
    s = Store(cfg.db_path)
    s.init_schema()
    _seed(s, load_taxonomy("v1"), uidvalidity=uidvalidity)
    s.close()
    import huginmail.cli as cli
    import huginmail.organize_imap as oi
    monkeypatch.setattr(cli, "load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(cli, "get_imap_password", lambda u: "pw")
    monkeypatch.setattr(oi, "ImapWriteSource", lambda *a, **k: fake)
    return cli


def test_cli_dry_run_makes_no_writes(monkeypatch, tmp_path):
    fake = FakeWriteSource()
    cli = _prime_cli(monkeypatch, tmp_path, fake)
    res = runner.invoke(cli.app, ["organize"])
    assert res.exit_code == 0
    assert "Dry-run" in res.output
    assert fake.applied == []          # nothing touched


def test_cli_apply_moves_present_uids(monkeypatch, tmp_path):
    fake = FakeWriteSource(present=(1, 2, 4))
    cli = _prime_cli(monkeypatch, tmp_path, fake)
    res = runner.invoke(cli.app, ["organize", "--apply"])
    assert res.exit_code == 0, res.output
    moved = {dest: uids for uids, dest, _ in fake.applied}
    assert moved == {"Newsletter": [1], "Receipt/Bank": [2], "Junk/Marketing": [4]}
    assert all(m == "move" for _, _, m in fake.applied)


def test_cli_apply_skips_already_gone(monkeypatch, tmp_path):
    fake = FakeWriteSource(present=(2, 4))   # uid 1 already moved out
    cli = _prime_cli(monkeypatch, tmp_path, fake)
    res = runner.invoke(cli.app, ["organize", "--apply"])
    assert res.exit_code == 0, res.output
    moved = {dest: uids for uids, dest, _ in fake.applied}
    assert moved["Newsletter"] == []          # skipped, no crash
    assert "already gone" in res.output


def test_cli_apply_aborts_on_uidvalidity_mismatch(monkeypatch, tmp_path):
    fake = FakeWriteSource(uidvalidity=999)   # store cursor has 42
    cli = _prime_cli(monkeypatch, tmp_path, fake, uidvalidity=42)
    res = runner.invoke(cli.app, ["organize", "--apply"])
    assert res.exit_code == 1
    assert "UIDVALIDITY mismatch" in res.output
    assert fake.applied == []                 # nothing moved
