# AGENTS.md — hugin-mail (root DOX)

## Purpose
Local-first, read-only email triage with local LLMs. Index a mailbox over IMAP,
classify with rules + a local LLM, produce reviewable reports. Spec:
`docs/prd/PRD_hugin-mail_v0.2.md`.

## Ownership
Root contract for the whole repo. Domain: sync, taxonomy, classification, reports.

## Local Contracts
- **v1 is strictly read-only.** No IMAP mutation of any kind (no STORE, EXPUNGE,
  COPY, flags, folders). `sync.py` enforces this via `MUTATING_COMMANDS` +
  `_assert_read_only`; every sync path must run through it.
- **No cloud LLM.** All inference local (OpenAI-compatible endpoint / Ollama).
- **Credentials** come from `HUGIN_IMAP_PASSWORD` or OS keychain — never config files.
- **Provenance is first-class.** Every `ClassificationRecord` stamps method,
  taxonomy version + hash, and (for LLM) model/prompt version.
- **Resolution order:** sender rule → keyword rule → LLM → `unclassified`.
- **Taxonomy is a versioned artifact** (`taxonomies/*.yaml`), not code; the
  rendered prompt form is token-budget-checked (`taxonomy.check_budget`).

## Work Guidance
- Stack: Python 3.12+, Typer, Pydantic v2 (frozen models), Polars, pytest.
- Small single-responsibility modules (≤ ~200 lines). Fully type-hinted.
  Comments only for non-obvious *why*. No speculative abstractions.
- Name files from `MAP.md`; do not roam the repo. One small task per change.
- Every CLI command idempotent + resumable.

## Verification
```bash
uv run pytest        # unit tests, per module
```

## Child DOX Index
No child AGENTS.md yet. `src/huginmail/` is a single flat domain owned here;
add a child doc only if a subtree grows its own durable contract.
