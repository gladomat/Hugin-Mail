# AGENTS.md — hugin-mail (root DOX)

## Purpose
Local-first email triage with local LLMs. Index a mailbox over IMAP, classify
with rules + a local LLM, review, and optionally organize (move messages to
folders). Spec: `docs/prd/PRD_hugin-mail_v0.2.md`.

## Ownership
Root contract for the whole repo. Domain: sync, taxonomy, classification, reports.

## Local Contracts
- **Indexing is strictly read-only.** The sync/index path performs no IMAP
  mutation (no STORE, EXPUNGE, COPY, flags, folders); `sync.py` enforces this
  via `MUTATING_COMMANDS` + `_assert_read_only`, and `sync_imap.py` selects
  EXAMINE + BODY.PEEK. Every sync path must run through the guard.
- **`organize` is the only mutating pass** and it is opt-in. Writes go solely
  through `organize_imap.ImapWriteSource` (standard IMAP MOVE/COPY), never the
  sync adapter. Contract: **provider-agnostic** (plain folder names, no
  Gmail/X-GM-LABELS), **dry-run by default** (`--apply` required to execute),
  aborts on UIDVALIDITY mismatch vs the sync cursor, only touches UIDs still
  present in the source folder (idempotent), and never deletes — junk routes to
  a configurable folder (`organize.junk_folder`), never Trash. Destinations come
  from `[organize]` config (auto Title-case of the leaf, or explicit `map`).
- **No cloud LLM.** All inference local (OpenAI-compatible endpoint / Ollama).
  Sampling profile sent explicitly per request; JSON validated by Pydantic;
  invalid → retry once → `unclassified`. Abstain below confidence over guessing.
- **Rules stored version-agnostic** (bare tag leaf); resolver validates each leaf
  against the current taxonomy and marks invalid rules `stale` rather than
  emitting a record against an undefined tag.
- **Credentials** come from `HUGIN_IMAP_PASSWORD` or OS keychain — never config files.
- **Provenance is first-class.** Every `ClassificationRecord` stamps method,
  taxonomy version + hash, and (for LLM) model/prompt version.
- **Resolution order:** sender rule → (keyword rule, only if
  `keyword_rules_authoritative`) → LLM → `unclassified`. **Default is
  LLM-first**: keyword rules are advisory hints (fed to the prompt), the model
  decides; confirmed sender rules always win. LLM calls below
  `llm.confidence_threshold` (default 0.7) abstain to `unclassified` (#18).
- **Taxonomy is a versioned artifact** (`taxonomies/*.yaml`), not code; the
  rendered prompt form is token-budget-checked (`taxonomy.check_budget`).

## Work Guidance
- Stack: Python 3.12+, Typer, Pydantic v2 (frozen models), Polars, Textual,
  openai (client only), pytest + pytest-asyncio.
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
