from __future__ import annotations

from typer.testing import CliRunner

from huginmail.cli import app

runner = CliRunner()


def test_version():
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0 and "hugin" in r.stdout


def test_status_on_empty_store(tmp_path, monkeypatch):
    monkeypatch.setenv("HUGIN_DATA_DIR", str(tmp_path))
    r = runner.invoke(app, ["status"])
    assert r.exit_code == 0
    assert "Messages indexed:  0" in r.stdout
    assert "LOCKED" in r.stdout


def test_taxonomy_command(tmp_path, monkeypatch):
    monkeypatch.setenv("HUGIN_DATA_DIR", str(tmp_path))
    r = runner.invoke(app, ["taxonomy"])
    assert r.exit_code == 0 and "v1" in r.stdout


def test_sync_without_config_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("HUGIN_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("HUGIN_IMAP_PASSWORD", raising=False)
    r = runner.invoke(app, ["sync"])
    assert r.exit_code == 1 and "IMAP not configured" in r.stdout
