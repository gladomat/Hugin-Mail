from __future__ import annotations

from huginmail.config import load_config


def test_defaults_when_no_file(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.data_dir == tmp_path
    assert cfg.imap.folders == ("INBOX",)
    assert cfg.llm.base_url.endswith("/v1")


def test_toml_overrides(tmp_path):
    (tmp_path / "config.toml").write_text(
        'taxonomy_version = "v1"\n'
        'store_full_bodies = true\n'
        '[imap]\nhost = "mail.acme.com"\nusername = "me@acme.com"\n'
        'folders = ["INBOX", "Archive"]\n'
        '[llm]\nmodel_id = "custom-8b"\n'
    )
    cfg = load_config(tmp_path)
    assert cfg.imap.host == "mail.acme.com"
    assert cfg.imap.folders == ("INBOX", "Archive")
    assert cfg.llm.model_id == "custom-8b"
    assert cfg.store_full_bodies is True


def test_llm_api_key_resolution(monkeypatch):
    from huginmail.config import get_llm_api_key
    monkeypatch.delenv("HUGIN_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert get_llm_api_key() == "not-needed"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    assert get_llm_api_key() == "sk-openai"
    monkeypatch.setenv("HUGIN_LLM_API_KEY", "hugin-key")
    assert get_llm_api_key() == "hugin-key"  # HUGIN_ wins


def test_credentials_never_in_config(tmp_path):
    (tmp_path / "config.toml").write_text('[imap]\nhost = "h"\npassword = "secret"\n')
    cfg = load_config(tmp_path)
    # password is not a field on ImapConfig; it must not leak onto the model
    assert not hasattr(cfg.imap, "password")
