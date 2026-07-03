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

### 5. Run the pipeline (LLM-first; each command idempotent + resumable)
```bash
hugin sync                     # Pass 0: read-only index (EXAMINE + BODY.PEEK)
hugin classify --all           # LLM classifies the whole inbox; uncertain → unclassified
hugin report summary           # SUMMARY.md — incl. lowest-confidence calls to review
# then correct only what's wrong, from the results:
hugin confirm --sender <name>  # override/defer specific senders (sender rules win)
hugin classify                 # re-apply; your corrections override the LLM
hugin audit                    # Pass 5: flag tag/keyword contradictions to review
hugin export rules --format sieve   # proposed sender→tag rules (never installed)
hugin status                   # coverage + modes, any time
```

Add `-v` to any command for debug logging; long runs (`sync`, `classify --all`)
show a live progress line. Classification is output-bound — to speed a full-inbox
run, raise `llm.concurrency` in config (e.g. `4`–`8`); oMLX continuous-batches
parallel requests, roughly multiplying throughput.

**LLM-first by default.** Confirmed sender rules always win; keyword rules are
*advisory* (they hint the model, they don't decide). You don't hand-review before
classifying — `classify --all` does the whole inbox, then you fix mistakes from
the output. Calls below the confidence threshold (default 0.7) land in
`unclassified` instead of guessing. Prefer the fast deterministic path? Set
`keyword_rules_authoritative = true` in config.

In the **`confirm` TUI**: `a` accept the hinted tag · `o` override (taxonomy leaf
like `receipt/bank`) · `d` defer with a note · `/` search · click a header to
sort · `q` quit. Per-decision writes — quitting loses nothing, re-running resumes.
A confirmed **domain** rule covers every address on that domain, tail included.

### Where things land
- `<data_dir>/reports/` — sender report.
- `<data_dir>/SUMMARY.md` — standing inbox overview (coverage, tag distribution,
  rule-leverage, top senders per tag), regenerated on every `classify`.
- `<data_dir>/exports/` — `manifest.parquet` + `manifest.csv` twin.
- `<data_dir>/hugin.sqlite` — all state. Delete the data dir to start over; your
  mailbox is untouched.

---

## Current status

Built: sync, taxonomy, sender report, confirm TUI (search/sort), LLM-first
classification (`classify --all`, advisory keyword rules, confidence abstention),
manifest + SUMMARY with a needs-review section.

**Not yet built:** #9 supervised gate (now opt-in, not required), #11 keyword
audit, #12 `export rules --format sieve`, #13 TOON batching, #17 progress/verbose
output. Everything is provenance-stamped (method, taxonomy version, model,
prompt) so any decision is traceable.

---

## Test
```bash
uv run pytest        # 68 tests
```
