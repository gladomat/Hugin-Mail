# hugin-mail

Local-first, provider-agnostic email triage with local LLMs. **v1 is strictly
read-only**: it indexes and classifies a mailbox over IMAP and produces
human-reviewable reports, but **never mutates server state** (no delete, move,
flag, or even marking as read). Nothing leaves your machine.

Full spec: `docs/prd/PRD_hugin-mail_v0.2.md`. Module map: `MAP.md`.

---

## What you have to do

### 1. Install
```bash
uv venv -p 3.13 && uv pip install -e ".[dev]"
source .venv/bin/activate      # or prefix commands with `uv run`
```

### 2. Create your config
```bash
hugin init-config              # writes <data_dir>/config.toml
```
Data dir defaults to `~/.local/share/hugin-mail` (override with `HUGIN_DATA_DIR`).
Edit the generated `config.toml`:
- `[imap]` — your `host`, `username`, and `folders`.
- `[llm]` — leave the oMLX default (`http://127.0.0.1:8000/v1`) or point at Ollama
  (`http://127.0.0.1:11434/v1`) and set `model_id`.

### 3. Provide the IMAP password (never in the config file)
```bash
export HUGIN_IMAP_PASSWORD='…'        # simplest; or store in the OS keychain:
# python -c "import keyring; keyring.set_password('hugin-mail','you@example.com','…')"
```

### 4. Start your local LLM
Run oMLX (or Ollama) so the endpoint in `config.toml` is live. Only needed for
the LLM classification steps (5c+), not for sync/rules.

### 5. Run the pipeline (each command is idempotent + resumable)
```bash
hugin sync                     # Pass 0: read-only index (EXAMINE + BODY.PEEK)
hugin report senders --top 100 # Pass 1: top-sender report (Markdown)
hugin confirm --top 100        # Pass 2: TUI review → sender/domain rules
hugin classify                 # apply rules (sender + keyword) → records + SUMMARY.md
hugin classify --batch 100     # LLM-classify up to N rule-uncovered messages
hugin status                   # coverage + gate states, any time
```

In the **`confirm` TUI**: `a` accept the hinted tag · `o` override (type a
taxonomy leaf like `receipt/bank`) · `d` defer with a note · `q` quit. Quitting
loses nothing — re-running resumes where you left off. A confirmed **domain**
rule covers every address on that domain, including the long tail.

### Where things land
- `<data_dir>/reports/` — sender report.
- `<data_dir>/SUMMARY.md` — standing inbox overview (coverage, tag distribution,
  rule-leverage, top senders per tag), regenerated on every `classify`.
- `<data_dir>/exports/` — `manifest.parquet` + `manifest.csv` twin.
- `<data_dir>/hugin.sqlite` — all state. Delete the data dir to start over; your
  mailbox is untouched.

---

## Current status

Built and merged/PR'd (issues #1–#8): sync, taxonomy, sender report, confirm
TUI, rules-classify, LLM client, `classify --batch`.

**Not yet built** (need decisions or later work):
- **#9 supervised gate** — needs your calls: spot-check agreement threshold
  (PRD default 95%), sample size, and whether a multilingual (DE/EN/RO) check
  gates Pass 4. This is the next step and is blocked on you.
- #10 unsupervised `classify --all`, #11 audit, #12 `export rules --format sieve`,
  #13 TOON batching (benchmark-gated), #14 comprehensive README.

The classification of rule-uncovered mail is only as good as your `confirm` pass
plus the local model; everything is provenance-stamped (method, taxonomy
version, model, prompt) so any decision is traceable.

---

## Test
```bash
uv run pytest        # 68 tests
```
