"""Runtime config. Credentials come from keychain/env only, never config files."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "hugin-mail"
KEYRING_SERVICE = "hugin-mail"


class ImapConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    host: str = ""
    port: int = 993
    username: str = ""
    folders: tuple[str, ...] = ("INBOX",)


class LlmConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    base_url: str = "http://127.0.0.1:8000/v1"
    model_id: str = "mlx-community/Qwen3-4B-Instruct"
    working_budget_tokens: int = 4096
    # LLM confidence below this lands in `unclassified` rather than a guess (§8).
    confidence_threshold: float = 0.7
    # Parallel in-flight classification requests (1 = sequential). Classification
    # is output-bound; oMLX continuous-batches, so >1 multiplies throughput.
    concurrency: int = 1


class Config(BaseModel):
    model_config = ConfigDict(frozen=True)

    data_dir: Path = Field(default=DEFAULT_DATA_DIR)
    taxonomy_version: str = "v1"
    imap: ImapConfig = ImapConfig()
    llm: LlmConfig = LlmConfig()
    store_full_bodies: bool = False
    # When False (default), keyword rules are advisory hints only and the LLM
    # decides; when True, they classify deterministically (fast path). See #18.
    keyword_rules_authoritative: bool = False

    @property
    def db_path(self) -> Path:
        return self.data_dir / "hugin.sqlite"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.reports_dir, self.exports_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_config(data_dir: Path | None = None) -> Config:
    """Build config from `<data_dir>/config.toml` if present, else defaults.

    Precedence for the data dir: explicit arg → `HUGIN_DATA_DIR` env → default.
    The TOML file holds `data_dir`, `taxonomy_version`, `store_full_bodies`, and
    `[imap]` / `[llm]` tables. Credentials are never read from it (keychain/env).
    """
    resolved = data_dir or _env_data_dir() or DEFAULT_DATA_DIR
    raw = _read_toml(resolved / "config.toml")
    if not raw:
        return Config(data_dir=resolved)

    raw.pop("data_dir", None)  # data dir is located, not self-referential
    imap = ImapConfig(**raw.pop("imap", {})) if "imap" in raw else ImapConfig()
    llm = LlmConfig(**raw.pop("llm", {})) if "llm" in raw else LlmConfig()
    return Config(data_dir=resolved, imap=imap, llm=llm, **raw)


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    import tomllib

    with path.open("rb") as fh:
        return tomllib.load(fh)


def _env_data_dir() -> Path | None:
    raw = os.environ.get("HUGIN_DATA_DIR")
    return Path(raw).expanduser() if raw else None


def get_llm_api_key() -> str:
    """Resolve the local LLM endpoint's API key. `HUGIN_LLM_API_KEY` first, then
    `OPENAI_API_KEY`, else a placeholder for servers that ignore auth."""
    return (os.environ.get("HUGIN_LLM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or "not-needed")


def get_imap_password(username: str) -> str | None:
    """Resolve IMAP password: env `HUGIN_IMAP_PASSWORD` first, then OS keychain."""
    env = os.environ.get("HUGIN_IMAP_PASSWORD")
    if env:
        return env
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, username)
    except Exception:
        return None
