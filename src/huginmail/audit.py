"""Pass 5: keyword audit. Deterministic scan for contradictions between a
message's assigned tag and the taxonomy's keyword signals — e.g. a `keep`
message full of `unsubscribe`/`% off` (suspected junk), or a `junk` message
saying `invoice` (suspected receipt). Findings go to a report for human review;
resolutions become new rules. Catches both sender-rule blind spots and LLM
misfiles."""

from __future__ import annotations

import logging
from pathlib import Path

from .models import AuditFinding, TagTaxonomy
from .store import Store

log = logging.getLogger(__name__)


def run_audit(store: Store, tax: TagTaxonomy) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    for msg in store.iter_messages():
        assigned = store.latest_tag(msg.folder, msg.uid, tax.content_hash)
        if assigned is None:
            continue
        haystack = f"{msg.subject}\n{msg.snippet}".lower()
        for rule in tax.keyword_rules:
            if rule.tag == assigned:
                continue
            matched = [kw for kw in rule.keywords if kw in haystack]
            if matched:
                findings.append(AuditFinding(
                    uid=msg.uid, folder=msg.folder, assigned_tag=assigned,
                    suspected_tag=rule.tag, trigger_keywords=tuple(matched)))
                break  # one finding per message (first contradicting rule)
    store.replace_audit_findings(findings)
    log.info("Audit: %d contradiction(s) found", len(findings))
    return findings


def write_audit_report(store: Store, findings: list[AuditFinding], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Audit findings",
        "",
        f"_{len(findings)} contradiction(s) between assigned tag and keyword signals_",
        "",
        "| Folder:UID | Assigned | Suspected | Trigger keywords |",
        "|------------|----------|-----------|------------------|",
    ]
    for f in findings:
        lines.append(f"| {f.folder}:{f.uid} | {f.assigned_tag} | {f.suspected_tag} "
                     f"| {', '.join(f.trigger_keywords)} |")
    path = out_dir / "audit.md"
    path.write_text("\n".join(lines) + "\n")
    return path
