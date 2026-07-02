"""Pydantic v2 data models. The SQLite schema mirrors these 1:1 (see store.py)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Method = Literal["sender_rule", "keyword_rule", "llm", "human"]


class EmailMessage(BaseModel):
    """One indexed message. No full body stored by default; snippet suffices."""

    model_config = ConfigDict(frozen=True)

    uid: int
    folder: str
    uidvalidity: int
    message_id: str
    from_addr: str
    from_domain: str
    to: str = ""
    subject: str = ""
    date: datetime | None = None
    size: int = 0
    snippet: str = ""
    headers_hash: str = ""


class SenderProfile(BaseModel):
    """Aggregate of a sender, derived from the message index via Polars."""

    model_config = ConfigDict(frozen=True)

    from_addr: str
    from_domain: str
    message_count: int
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    keyword_hint: str | None = None
    example_subjects: tuple[str, ...] = ()
    confirmed_tag: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None


class ClassificationRecord(BaseModel):
    """Append-only classification. Latest wins per taxonomy version."""

    model_config = ConfigDict(frozen=True)

    uid: int
    folder: str
    tag: str
    subtags: tuple[str, ...] = ()
    confidence: float = 1.0
    method: Method
    taxonomy_version: str
    taxonomy_hash: str
    model_id: str | None = None
    prompt_version: str | None = None
    rationale: str | None = None
    truncated: bool = False
    created_at: datetime


class AuditFinding(BaseModel):
    """A keyword/tag contradiction surfaced by the audit pass."""

    model_config = ConfigDict(frozen=True)

    uid: int
    folder: str
    assigned_tag: str
    suspected_tag: str
    trigger_keywords: tuple[str, ...]
    resolved: bool = False


Scope = Literal["addr", "domain"]


class SenderRule(BaseModel):
    """A human-confirmed classification rule bound to an address or a domain.

    Highest-precedence classification source. `tag`/`subtag` reference a leaf in
    the current taxonomy but are stored version-agnostically (validated at
    classify time; migrated by changelog on a major bump)."""

    model_config = ConfigDict(frozen=True)

    key: str  # lowercased address or domain
    scope: Scope
    tag: str
    subtag: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None

    @property
    def leaf(self) -> str:
        return f"{self.tag}/{self.subtag}" if self.subtag else self.tag


class Deferral(BaseModel):
    """A sender parked during confirm with a free-text note — a queue signal for
    a later taxonomy decision, never a classification source."""

    model_config = ConfigDict(frozen=True)

    key: str
    scope: Scope
    note: str = ""
    created_at: datetime | None = None


class KeywordRule(BaseModel):
    """A keyword condition attached to a tag in the taxonomy."""

    model_config = ConfigDict(frozen=True)

    tag: str
    keywords: tuple[str, ...]
    fields: tuple[Literal["subject", "from_addr", "snippet"], ...] = ("subject",)


class TagNode(BaseModel):
    """A tag (or subtag) definition."""

    model_config = ConfigDict(frozen=True)

    name: str
    definition: str
    subtags: tuple[str, ...] = ()


class TagTaxonomy(BaseModel):
    """Versioned tag taxonomy. Loaded from YAML, hashed into every record."""

    model_config = ConfigDict(frozen=True)

    version: str
    tags: tuple[TagNode, ...]
    keyword_rules: tuple[KeywordRule, ...] = ()
    changelog: str = ""
    content_hash: str = ""
