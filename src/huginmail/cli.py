"""Typer CLI. Every command is idempotent and resumable (PRD §11)."""

from __future__ import annotations

import typer

from . import __version__
from .config import Config, get_imap_password, load_config
from .report import write_sender_report
from .store import Store
from .sync import sync_folder
from .taxonomy import check_budget, load_taxonomy

app = typer.Typer(help="hugin — local-first, read-only email triage", no_args_is_help=True)
report_app = typer.Typer(help="Generate reports")
app.add_typer(report_app, name="report")


@app.callback()
def main(
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Debug-level logging"),
    quiet: bool = typer.Option(False, "-q", "--quiet", help="Warnings only"),
) -> None:
    """Configure logging before any command runs."""
    from .log import configure

    configure(verbosity=int(verbose), quiet=quiet)


def _tty() -> bool:
    import sys

    return sys.stderr.isatty()


def _open(cfg: Config) -> Store:
    cfg.ensure_dirs()
    store = Store(cfg.db_path)
    store.init_schema()
    return store


@app.command()
def version() -> None:
    """Print version."""
    typer.echo(f"hugin {__version__}")


_CONFIG_TEMPLATE = """\
# hugin-mail config. Credentials are NEVER stored here — set the IMAP password
# via the HUGIN_IMAP_PASSWORD env var or the OS keychain (service "hugin-mail").
taxonomy_version = "v1"
store_full_bodies = false
# false (default): keyword rules are advisory, the LLM decides. true: keyword
# rules classify deterministically (fast path, but crude — can misfile).
keyword_rules_authoritative = false

[imap]
host = "imap.example.com"
port = 993
username = "you@example.com"
folders = ["INBOX"]

[llm]
base_url = "http://127.0.0.1:8000/v1"   # oMLX default; Ollama: http://127.0.0.1:11434/v1
model_id = "mlx-community/Qwen3-4B-Instruct"
working_budget_tokens = 4096
confidence_threshold = 0.7              # LLM calls below this land in `unclassified`
concurrency = 1                         # parallel in-flight requests (raise to ~4)
max_tokens = 75                         # output cap; lower = faster (output-bound)
rationale = "terse"                     # terse (<=6 words) | full | off
"""


@app.command("init-config")
def init_config() -> None:
    """Write a starter config.toml into the data dir (does not overwrite)."""
    cfg = load_config()
    cfg.ensure_dirs()
    path = cfg.data_dir / "config.toml"
    if path.exists():
        typer.secho(f"{path} already exists — leaving it untouched.",
                    fg=typer.colors.YELLOW)
        raise typer.Exit(0)
    path.write_text(_CONFIG_TEMPLATE)
    typer.echo(f"Wrote {path}")
    typer.echo("Edit imap.host/username + llm settings, then set "
               "HUGIN_IMAP_PASSWORD (or store it in the keychain).")


@app.command()
def status() -> None:
    """Show sync + classification coverage and gate states."""
    cfg = load_config()
    store = _open(cfg)
    total = store.message_count()
    distinct = store.distinct_message_count()
    classified = store.classification_count()
    coverage = (classified / distinct * 100) if distinct else 0.0

    tax = load_taxonomy(cfg.taxonomy_version)
    typer.echo(f"Data dir:          {cfg.data_dir}")
    typer.echo(f"Taxonomy:          {tax.version} ({tax.content_hash})")
    typer.echo(f"Messages indexed:  {total} ({distinct} distinct)")
    typer.echo(f"Classified:        {classified} ({coverage:.1f}% of distinct)")
    typer.echo("")
    typer.echo("Folders:")
    for folder in cfg.imap.folders:
        cur = store.get_cursor(folder)
        if cur is None:
            typer.echo(f"  {folder}: not synced")
        else:
            state = "complete" if cur["complete"] else "incomplete"
            typer.echo(f"  {folder}: {state} (uidvalidity={cur['uidvalidity']}, "
                       f"last_uid={cur['last_uid']})")
    typer.echo("")
    mode = ("authoritative" if cfg.keyword_rules_authoritative else "advisory (LLM decides)")
    typer.echo("Modes:")
    typer.echo(f"  keyword_rules: {mode}")
    typer.echo(f"  llm abstain below confidence: {cfg.llm.confidence_threshold}")
    store.close()


@app.command()
def sync(
    folder: str = typer.Option(None, help="Folder to sync (default: config folders)"),
    full: bool = typer.Option(False, help="Ignore cursor; re-index the whole folder"),
) -> None:
    """Pass 0: index a folder over read-only IMAP (EXAMINE + BODY.PEEK)."""
    cfg = load_config()
    store = _open(cfg)
    tax = load_taxonomy(cfg.taxonomy_version)
    folders = [folder] if folder else list(cfg.imap.folders)

    password = get_imap_password(cfg.imap.username)
    if not cfg.imap.host or not password:
        typer.secho(
            "IMAP not configured. Set imap.host/username in config and provide the "
            "password via HUGIN_IMAP_PASSWORD or the OS keychain.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    from .sync_imap import ImapToolsSource

    source = ImapToolsSource(cfg.imap.host, cfg.imap.port, cfg.imap.username, password)
    try:
        for f in folders:
            if _tty():
                from rich.progress import Progress, SpinnerColumn, TextColumn

                with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                              transient=True) as prog:
                    task = prog.add_task(f"{f}: fetching…", total=None)
                    res = sync_folder(store, source, tax, f, full=full,
                                      on_fetch=lambda n: prog.update(
                                          task, description=f"{f}: {n} fetched…"))
            else:
                res = sync_folder(store, source, tax, f, full=full)
            typer.echo(
                f"{f}: fetched={res.fetched} inserted={res.inserted} "
                f"deduped={res.deduped} uidvalidity={res.uidvalidity}"
                + (" [resynced]" if res.resynced else "")
            )
    finally:
        source.close()
        store.close()


@app.command()
def confirm(
    top: int = typer.Option(100, help="Review the top-N senders"),
    sender: str = typer.Option(
        None, help="Restrict the queue to senders matching this substring "
                   "(any rank; reaches the long tail)"),
    source: str = typer.Option("report", help="report | batch (batch = Pass 3, later)"),
) -> None:
    """Pass 2: review senders in a TUI; confirmed decisions become rules."""
    if source != "report":
        typer.secho("Only --source report is supported in v1 (batch = S7).",
                    fg=typer.colors.RED)
        raise typer.Exit(1)
    cfg = load_config()
    store = _open(cfg)
    tax = load_taxonomy(cfg.taxonomy_version)
    if store.message_count() == 0:
        typer.secho("No messages indexed. Run `hugin sync` first.",
                    fg=typer.colors.RED)
        raise typer.Exit(1)

    from .confirm import ConfirmSession
    from .confirm_tui import run_confirm

    session = ConfirmSession(store, tax, top)
    run_confirm(session, sender_filter=sender)
    cov = session.coverage()
    typer.echo(f"Rules now project {cov.covered}/{cov.total} "
               f"({cov.fraction * 100:.1f}%) coverage.")
    if cov.below_target:
        typer.secho("Below the 60% Phase-1b target — more senders await review.",
                    fg=typer.colors.YELLOW)
    store.close()


@app.command()
def classify(
    batch: int = typer.Option(
        None, help="LLM-classify up to N rule-uncovered messages"),
    all_: bool = typer.Option(
        False, "--all", help="LLM-classify every rule-uncovered message (whole inbox)"),
) -> None:
    """Classify the inbox. Confirmed sender rules always win; by default keyword
    rules are advisory and the LLM decides the rest (config:
    keyword_rules_authoritative). Use --all to let the LLM do the whole inbox in
    one pass, or --batch N for a bounded run. With neither, only rules are applied."""
    cfg = load_config()
    store = _open(cfg)
    tax = load_taxonomy(cfg.taxonomy_version)
    kw = cfg.keyword_rules_authoritative

    from .classify import classify_llm_batch, classify_rules
    from .export import export_manifest
    from .summary import write_summary

    res = classify_rules(store, tax, keyword_authoritative=kw)
    typer.echo(f"Rules: scanned={res.scanned} written={res.written} "
               f"unchanged={res.unchanged} uncovered={res.uncovered}")

    if all_ or batch is not None:
        from .llm import OpenAiClient

        limit = None if all_ else batch
        scope = "whole inbox" if all_ else f"up to {batch}"
        typer.echo(f"LLM classifying {scope} "
                   f"(model={cfg.llm.model_id}, abstain<{cfg.llm.confidence_threshold})…")
        client = OpenAiClient(cfg.llm)
        on_item = None
        if _tty():
            from rich.progress import Progress, SpinnerColumn, TextColumn

            prog = Progress(SpinnerColumn(), TextColumn("{task.description}"),
                            transient=True)
            prog.start()
            task = prog.add_task("classifying…", total=None)
            on_item = lambda n, tag, conf: prog.update(
                task, description=f"{n} classified (last: {tag} {conf:.2f})")
        bres = classify_llm_batch(
            store, tax, client, cfg.llm, limit=limit, keyword_authoritative=kw,
            confidence_threshold=cfg.llm.confidence_threshold, on_item=on_item,
            concurrency=cfg.llm.concurrency)
        if on_item is not None:
            prog.stop()
        typer.echo(f"LLM: called={bres.called} unclassified={bres.unclassified}")

    export_manifest(store, tax, cfg.exports_dir)
    summ = write_summary(store, tax, cfg.data_dir)
    typer.echo(f"Wrote {summ} and manifest (parquet + csv) to {cfg.exports_dir}")
    store.close()


@report_app.command("senders")
def report_senders(top: int = typer.Option(100, help="Number of top senders")) -> None:
    """Pass 1: top-N sender report (Markdown)."""
    cfg = load_config()
    store = _open(cfg)
    tax = load_taxonomy(cfg.taxonomy_version)
    path = write_sender_report(store, cfg.reports_dir, tax.version, top)
    typer.echo(f"Wrote {path}")
    store.close()


@report_app.command("summary")
def report_summary() -> None:
    """Regenerate SUMMARY.md — the standing inbox overview."""
    cfg = load_config()
    store = _open(cfg)
    tax = load_taxonomy(cfg.taxonomy_version)
    from .summary import write_summary

    path = write_summary(store, tax, cfg.data_dir)
    typer.echo(f"Wrote {path}")
    store.close()


export_app = typer.Typer(help="Exports")
app.add_typer(export_app, name="export")


@export_app.command("manifest")
def export_manifest_cmd() -> None:
    """Export the classification manifest (Parquet + CSV twin)."""
    cfg = load_config()
    store = _open(cfg)
    tax = load_taxonomy(cfg.taxonomy_version)
    from .export import export_manifest

    parquet, csv = export_manifest(store, tax, cfg.exports_dir)
    typer.echo(f"Wrote {parquet} and {csv}")
    store.close()


@export_app.command("rules")
def export_rules_cmd(
    format: str = typer.Option("text", help="text | sieve"),
) -> None:
    """Export proposed sender→tag rules (never installed; v1 is read-only)."""
    cfg = load_config()
    store = _open(cfg)
    from .export import export_rules

    path = export_rules(store, cfg.exports_dir, fmt=format)
    typer.echo(f"Wrote {path}")
    store.close()


@app.command()
def audit() -> None:
    """Pass 5: scan for tag/keyword contradictions → audit report."""
    cfg = load_config()
    store = _open(cfg)
    tax = load_taxonomy(cfg.taxonomy_version)
    from .audit import run_audit, write_audit_report
    from .summary import write_summary

    findings = run_audit(store, tax)
    path = write_audit_report(store, findings, cfg.reports_dir)
    write_summary(store, tax, cfg.data_dir)
    typer.echo(f"Audit: {len(findings)} finding(s). Wrote {path}")
    store.close()


@app.command()
def taxonomy() -> None:
    """Show the active taxonomy and its rendered token budget."""
    cfg = load_config()
    tax = load_taxonomy(cfg.taxonomy_version)
    used = check_budget(tax)
    typer.echo(f"Taxonomy {tax.version} ({tax.content_hash})")
    typer.echo(f"Tags: {', '.join(t.name for t in tax.tags)}")
    typer.echo(f"Rendered budget: {used} tokens")


if __name__ == "__main__":
    app()
