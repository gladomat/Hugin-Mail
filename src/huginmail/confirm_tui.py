"""Textual TUI for `hugin confirm`. Thin driver over ConfirmSession (all rule
logic lives there). Testable via Textual's Pilot harness."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header, Input, Static

from .confirm import ConfirmSession, LeafError, QueueItem

_COLS = ("scope", "sender / domain", "count", "hint", "status", "decision")


class ConfirmApp(App):
    """Review top-N senders; accept / override / defer, one keystroke each."""

    CSS = "#entry { display: none; } #entry.on { display: block; }"
    BINDINGS = [
        ("a", "accept", "Accept hint"),
        ("o", "override", "Override"),
        ("d", "defer", "Defer"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, session: ConfirmSession) -> None:
        super().__init__()
        self.session = session
        self.items: list[QueueItem] = []
        self._mode: str | None = None  # 'override' | 'defer'

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="grid", cursor_type="row")
        yield Input(id="entry", placeholder="")
        yield Static("", id="cov")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#grid", DataTable)
        table.add_columns(*_COLS)
        self.refresh_queue()

    # --- rendering ------------------------------------------------------
    def refresh_queue(self) -> None:
        table = self.query_one("#grid", DataTable)
        row = table.cursor_row
        table.clear()
        self.items = self.session.build_queue()
        for it in self.items:
            table.add_row(
                it.scope, it.label, str(it.message_count), it.hint or "—",
                it.status, it.current_leaf or (it.note and f"defer:{it.note}") or "—",
            )
        if self.items:
            table.move_cursor(row=min(row, len(self.items) - 1))
        self._update_coverage()

    def _update_coverage(self) -> None:
        cov = self.session.coverage()
        flag = "  ⚠ below 60% target" if cov.below_target else ""
        self.query_one("#cov", Static).update(
            f"Projected coverage: {cov.covered}/{cov.total} "
            f"({cov.fraction * 100:.1f}%){flag}"
        )

    def _current(self) -> QueueItem | None:
        if not self.items:
            return None
        idx = self.query_one("#grid", DataTable).cursor_row
        return self.items[idx] if 0 <= idx < len(self.items) else None

    # --- actions --------------------------------------------------------
    def action_accept(self) -> None:
        it = self._current()
        if it is None:
            return
        try:
            self.session.accept(it)
        except LeafError as e:
            self._notify(str(e))
            return
        self.refresh_queue()

    def action_override(self) -> None:
        self._open_input("override", "tag or tag/subtag (e.g. receipt/bank)")

    def action_defer(self) -> None:
        self._open_input("defer", "note (why deferred)")

    def _open_input(self, mode: str, placeholder: str) -> None:
        if self._current() is None:
            return
        self._mode = mode
        entry = self.query_one("#entry", Input)
        entry.placeholder = placeholder
        entry.value = ""
        entry.add_class("on")
        entry.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        it = self._current()
        entry = self.query_one("#entry", Input)
        entry.remove_class("on")
        mode, self._mode = self._mode, None
        if it is None or mode is None:
            return
        try:
            if mode == "override":
                self.session.set_rule(it.key, it.scope, event.value)
            elif mode == "defer":
                self.session.defer(it.key, it.scope, event.value)
        except LeafError as e:
            self._notify(str(e))
        self.query_one("#grid", DataTable).focus()
        self.refresh_queue()

    def _notify(self, msg: str) -> None:
        self.query_one("#cov", Static).update(f"⚠ {msg}")


def run_confirm(session: ConfirmSession) -> None:
    ConfirmApp(session).run()
