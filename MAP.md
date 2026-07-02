# MAP — one module, one responsibility

Quote paths from here when naming files for a task (PRD §12). Keep modules
≤ ~200 lines; if one outgrows that, it's a design smell.

## src/huginmail/

| Module | Responsibility |
|--------|----------------|
| `__init__.py` | Package + version |
| `config.py` | Runtime config, data dir, credential resolution (keychain/env only) |
| `models.py` | Pydantic v2 models; SQLite schema mirrors these 1:1 |
| `store.py` | SQLite store: messages, cursors, rules, classifications, findings |
| `tokens.py` | Offline token estimator (taxonomy budget check only) |
| `taxonomy.py` | Load/hash/render/budget-check the versioned taxonomy |
| `taxonomies/*.yaml` | Versioned taxonomy artifacts (data, not code) |
| `hints.py` | Deterministic keyword-hint from taxonomy rules (Pass 0) |
| `sync.py` | Read-only sync engine + `ImapSource` protocol + mutation guard |
| `sync_imap.py` | Real imap-tools adapter (EXAMINE + BODY.PEEK) |
| `report.py` | Polars sender aggregation + top-N Markdown report (Pass 1) |
| `cli.py` | Typer CLI: `status`, `sync`, `report senders`, `taxonomy` |

## tests/
Mirror per module. `conftest.py` provides `store`, `tax`, and `FakeImapSource`.

## Not yet built (see GitHub issues #5–#13)
Confirm/rules engine, rules-classify + manifest + SUMMARY.md, LLM client,
classify commands, supervised gate, unsupervised, audit, export rules, TOON.
