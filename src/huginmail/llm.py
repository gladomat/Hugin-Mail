"""LLM runtime (§9): OpenAI-compatible client, explicit per-request sampling
profile, context budget + deterministic truncation, JSON structured output with
Pydantic validation and retry-once-then-unclassified.

The engine works against the `LlmClient` protocol so it is testable without a
live endpoint. `OpenAiClient` is the real adapter (oMLX / Ollama / any
OpenAI-compatible server)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import Protocol

from pydantic import BaseModel, Field, ValidationError

from .config import LlmConfig
from .hints import keyword_hint
from .models import EmailMessage, TagTaxonomy
from .rules import valid_leaves
from .taxonomy import render_prompt
from .tokens import estimate_tokens

PROMPT_VERSION = "classify_v1"

# Per-request sampling — sent explicitly, never relying on server defaults (§9).
SAMPLING = {"temperature": 0.0, "top_p": 1.0, "max_tokens": 200}

# Fixed token allocation (§9.1).
PAYLOAD_BUDGET = 300


class LlmResponse(BaseModel):
    tag: str
    subtags: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    rationale: str = ""


@dataclass(frozen=True)
class LlmOutcome:
    tag: str
    subtag: str | None
    confidence: float
    rationale: str
    truncated: bool
    model_id: str
    prompt_version: str = PROMPT_VERSION


class LlmClient(Protocol):
    def complete(self, system: str, user: str, sampling: dict) -> str:
        """Return the model's raw text content (expected: a JSON object)."""


def load_prompt(version: str = PROMPT_VERSION) -> str:
    return resources.files("huginmail.prompts").joinpath(f"{version}.txt").read_text()


def build_payload(msg: EmailMessage, budget: int = PAYLOAD_BUDGET) -> tuple[str, bool]:
    """Render the message payload, tail-truncating the snippet to fit budget."""
    head = (f"From: {msg.from_addr}\nSubject: {msg.subject}\n"
            f"Date: {msg.date.isoformat() if msg.date else ''}\nSnippet: ")
    room = budget - estimate_tokens(head)
    snippet = msg.snippet
    truncated = False
    while snippet and estimate_tokens(snippet) > max(room, 0):
        snippet = snippet[: max(len(snippet) - 32, 0)]
        truncated = True
    return head + snippet, truncated


def classify_message(
    client: LlmClient, tax: TagTaxonomy, msg: EmailMessage, cfg: LlmConfig,
) -> LlmOutcome:
    system = load_prompt().format(taxonomy=render_prompt(tax))
    payload, truncated = build_payload(msg)
    hint = keyword_hint(msg, tax)
    if hint:
        payload += f"\nKeyword hint (advisory, may be wrong): {hint}"
    leaves = valid_leaves(tax)

    parsed = _try_classify(client, system, payload)
    if parsed is None:
        parsed = _try_classify(client, system, payload)  # retry once

    if parsed is None or parsed.tag not in leaves:
        return LlmOutcome("unclassified", None, 0.0, "", truncated, cfg.model_id)

    subtag = next((s.split("/", 1)[1] for s in parsed.subtags
                   if s in leaves and "/" in s), None)
    return LlmOutcome(parsed.tag, subtag, parsed.confidence, parsed.rationale,
                      truncated, cfg.model_id)


def _try_classify(client: LlmClient, system: str, payload: str) -> LlmResponse | None:
    try:
        raw = client.complete(system, payload, SAMPLING)
        return LlmResponse.model_validate_json(_extract_json(raw))
    except (ValidationError, json.JSONDecodeError, ValueError):
        return None


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in response")
    return text[start : end + 1]


class OpenAiClient:
    """Adapter over any OpenAI-compatible chat-completions endpoint (oMLX/Ollama)."""

    def __init__(self, cfg: LlmConfig) -> None:
        from openai import OpenAI

        self.cfg = cfg
        self._client = OpenAI(base_url=cfg.base_url, api_key="not-needed")

    def complete(self, system: str, user: str, sampling: dict) -> str:
        resp = self._client.chat.completions.create(
            model=self.cfg.model_id,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            **sampling,
        )
        return resp.choices[0].message.content or ""
