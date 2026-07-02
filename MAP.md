# MAP — one module, one responsibility

Quote paths from here when naming files for a task (PRD §12). Keep modules
≤ ~200 lines; if one outgrows that, it's a design smell.

## src/huginmail/

| Module | Responsibility |
|--------|----------------|
| `__init__.py` | Package + version |
| `config.py` | Runtime config (TOML file + env), data dir, credential resolution (keychain/env only) |
| `models.py` | Pydantic v2 models; SQLite schema mirrors these 1:1 |
| `store.py` | SQLite store: messages, cursors, rules, classifications, findings |
| `tokens.py` | Offline token estimator (taxonomy budget check only) |
| `taxonomy.py` | Load/hash/render/budget-check the versioned taxonomy |
| `taxonomies/*.yaml` | Versioned taxonomy artifacts (data, not code) |
| `hints.py` | Deterministic keyword-hint from taxonomy rules (Pass 0) |
| `sync.py` | Read-only sync engine + `ImapSource` protocol + mutation guard |
| `sync_imap.py` | Real imap-tools adapter (EXAMINE + BODY.PEEK) |
| `report.py` | Polars sender aggregation + top-N Markdown report (Pass 1) |
| `rules.py` | `Resolver`: address→domain→keyword→LLM order; leaf validation |
| `confirm.py` | Pass 2 session logic (queue, accept/override/defer, coverage) — UI-free |
| `confirm_tui.py` | Textual TUI driver over `ConfirmSession` |
| `classify.py` | Rules pass (`classify_rules`) + LLM batch (`classify_llm_batch`) |
| `llm.py` | `LlmClient` protocol, `OpenAiClient`, sampling, budget, JSON+retry |
| `prompts/*.txt` | Versioned prompt templates (`prompt_version`) |
| `export.py` | Manifest → Parquet + CSV twin |
| `summary.py` | `SUMMARY.md` standing overview |
| `cli.py` | Typer CLI: `init-config`, `status`, `sync`, `confirm`, `classify`, `report`, `export`, `taxonomy` |

## tests/
Mirror per module. `conftest.py` provides `store`, `tax`, `FakeImapSource`.
LLM tests use an in-file `FakeClient`; TUI tests use Textual `Pilot`.

## Not yet built (see GitHub issues #9–#14)
Supervised gate (#9), unsupervised classify (#10), audit (#11), export rules
(#12), TOON (#13), comprehensive README (#14).
