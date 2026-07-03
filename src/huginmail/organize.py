"""Plan the writeback pass: map each message's winning leaf to a destination
IMAP folder. Pure/testable — no server contact. The apply side lives in
`organize_imap.py`; the CLI wires them together (dry-run by default)."""

from __future__ import annotations

from dataclasses import dataclass

from .config import OrganizeConfig
from .models import TagTaxonomy
from .store import Store


@dataclass(frozen=True)
class OrganizeAction:
    """One intended folder change. `dest` is a plain IMAP folder name."""

    folder: str          # source folder the message currently lives in
    uid: int
    message_id: str
    subject: str
    leaf: str            # winning classification, e.g. 'newsletter' or 'receipt/bank'
    dest: str            # destination folder


def _leaf_of(tag: str, subtags_csv: str | None) -> str:
    """Winning leaf for a message: 'tag' or 'tag/subtag' (first subtag only)."""
    subs = [s for s in (subtags_csv or "").split(",") if s]
    return f"{tag}/{subs[0]}" if subs else tag


def _titlecase_path(leaf: str) -> str:
    """'receipt/bank' → 'Receipt/Bank'. Deterministic; no pluralisation (that's
    a naming opinion left to the user's `[organize.map]` overrides)."""
    return "/".join(seg[:1].upper() + seg[1:] for seg in leaf.split("/"))


def dest_for(leaf: str, cfg: OrganizeConfig) -> str | None:
    """Resolve a leaf to a destination folder, or None to leave it in place.

    Precedence: skip-tags → explicit leaf map → explicit tag map → junk →
    auto Title-case."""
    tag = leaf.split("/", 1)[0]
    if leaf in cfg.skip_tags or tag in cfg.skip_tags:
        return None
    if leaf in cfg.map:
        return cfg.map[leaf]
    subtag = leaf.split("/", 1)[1] if "/" in leaf else ""
    if tag in cfg.map:
        base = cfg.map[tag]
        return f"{base}/{_titlecase_path(subtag)}" if subtag else base
    if tag == "junk":
        base = cfg.junk_folder
        return f"{base}/{_titlecase_path(subtag)}" if subtag else base
    return _titlecase_path(leaf)


def plan_actions(store: Store, tax: TagTaxonomy,
                 cfg: OrganizeConfig) -> list[OrganizeAction]:
    """Every intended move for messages currently in `cfg.source_folder`,
    based on the latest (human-wins) classification per message."""
    actions: list[OrganizeAction] = []
    for row in store.manifest_rows(tax.content_hash):
        if row["folder"] != cfg.source_folder:
            continue
        leaf = _leaf_of(row["tag"], row["subtags"])
        dest = dest_for(leaf, cfg)
        if dest is None or dest == row["folder"]:
            continue
        actions.append(OrganizeAction(
            folder=row["folder"], uid=int(row["uid"]),
            message_id=row["message_id"] or "", subject=row["subject"] or "",
            leaf=leaf, dest=dest,
        ))
    return actions
