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

[imap]
host = "imap.example.com"
port = 993
username = "you@example.com"
folders = ["INBOX"]

[llm]
base_url = "http://127.0.0.1:8000/v1"   # oMLX default; Ollama: http://127.0.0.1:11434/v1
model_id = "mlx-community/Qwen3-4B-Instruct"
working_budget_tokens = 4096
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
    typer.echo("Gates:")
    typer.echo("  unsupervised_classify: LOCKED (Pass 3 spot-check not run)")
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
        None, help="Also LLM-classify up to N rule-uncovered messages (Pass 3)"),
) -> None:
    """Apply confirmed rules (sender + keyword) over the index. With --batch,
    the local LLM then classifies up to N rule-uncovered messages (K=1)."""
    cfg = load_config()
    store = _open(cfg)
    tax = load_taxonomy(cfg.taxonomy_version)

    from .classify import classify_llm_batch, classify_rules
    from .export import export_manifest
    from .summary import write_summary

    res = classify_rules(store, tax)
    typer.echo(f"Rules: scanned={res.scanned} written={res.written} "
               f"unchanged={res.unchanged} uncovered={res.uncovered}")
    if batch is not None:
        from .llm import OpenAiClient

        client = OpenAiClient(cfg.llm)
        bres = classify_llm_batch(store, tax, client, cfg.llm, limit=batch)
        typer.echo(f"LLM batch: called={bres.called} "
                   f"unclassified={bres.unclassified}")

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
