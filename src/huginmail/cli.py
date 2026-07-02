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


@report_app.command("senders")
def report_senders(top: int = typer.Option(100, help="Number of top senders")) -> None:
    """Pass 1: top-N sender report (Markdown)."""
    cfg = load_config()
    store = _open(cfg)
    tax = load_taxonomy(cfg.taxonomy_version)
    path = write_sender_report(store, cfg.reports_dir, tax.version, top)
    typer.echo(f"Wrote {path}")
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
