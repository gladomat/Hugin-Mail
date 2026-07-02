# hugin-mail

Local-first, provider-agnostic email triage with local LLMs. **v1 is strictly
read-only**: it indexes and classifies a mailbox over IMAP and produces
human-reviewable reports, but never mutates server state.

See `docs/prd/PRD_hugin-mail_v0.2.md` for the full spec.

## Install (dev)

```bash
uv venv && uv pip install -e ".[dev]"
```

## Usage

```bash
hugin status                 # sync/classification coverage, gate states
hugin taxonomy               # active taxonomy + rendered token budget
hugin sync --folder INBOX    # Pass 0: read-only index (EXAMINE + BODY.PEEK)
hugin report senders --top 100   # Pass 1: top-sender Markdown report
hugin confirm --top 100      # Pass 2: TUI review → sender/domain rules
hugin classify               # apply rules (sender + keyword) → records
hugin classify --batch 100   # + LLM-classify up to N rule-uncovered messages
hugin report summary         # regenerate SUMMARY.md
hugin export manifest        # manifest.parquet + manifest.csv
```

Reports land in `<data_dir>/reports`, exports in `<data_dir>/exports`,
`SUMMARY.md` in the data dir root.

Config data dir defaults to `~/.local/share/hugin-mail` (override with
`HUGIN_DATA_DIR`). IMAP credentials come from `HUGIN_IMAP_PASSWORD` or the OS
keychain — never config files.

## Test

```bash
uv run pytest
```
