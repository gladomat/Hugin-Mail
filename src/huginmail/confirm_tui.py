"""Textual TUI for `hugin confirm`. Thin driver over ConfirmSession (all rule
logic lives there). Testable via Textual's Pilot harness.

Layout: the grid fills remaining space (`height: 1fr`) and scrolls internally;
the coverage line + input are docked to the bottom so they are always visible.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import DataTable, Footer, Header, Input, Static

from .confirm import ConfirmSession, LeafError, QueueItem

_COLS = ("scope", "sender / domain", "count", "hint", "status", "decision")

# View-layer sort keys per column index. Column 2 (count) sorts numerically.
_SORT_KEYS = {
    0: lambda it: it.scope,
    1: lambda it: it.label.lower(),
    2: lambda it: it.message_count,
    3: lambda it: (it.hint or ""),
    4: lambda it: it.status,
    5: lambda it: (it.current_leaf or it.note or ""),
}


class ConfirmApp(App):
    """Review top-N senders; accept / override / defer, one keystroke each."""

    CSS = """
    #grid { height: 1fr; }
    #bottom { dock: bottom; height: auto; }
    #entry { display: none; }
    #entry.on { display: block; }
    """
    BINDINGS = [
        ("a", "accept", "Accept hint"),
        ("o", "override", "Override"),
        ("d", "defer", "Defer"),
        ("slash", "search", "Search"),
        ("q", "quit", "Quit"),
        Binding("escape", "cancel_input", "Cancel", priority=True),
    ]

    def __init__(self, session: ConfirmSession, sender_filter: str | None = None) -> None:
        super().__init__()
        self.session = session
        self.sender_filter = sender_filter  # launch filter (reaches any rank)
        self.search_text = ""               # live `/` filter over the loaded queue
        self.sort_col: int | None = None
        self.sort_desc = False
        self.items: list[QueueItem] = []
        self._mode: str | None = None       # 'override' | 'defer' | 'search'

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="grid", cursor_type="row")
        with Container(id="bottom"):
            yield Static("", id="cov")
            yield Input(id="entry", placeholder="")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_queue()

    # --- rendering ------------------------------------------------------
    def refresh_queue(self) -> None:
        table = self.query_one("#grid", DataTable)
        prev = table.cursor_row
        table.clear(columns=True)
        table.add_columns(*self._headers())

        items = self.session.build_queue(self.sender_filter)
        if self.search_text:
            s = self.search_text.lower()
            items = [it for it in items if s in it.label.lower() or s in it.key.lower()]
        if self.sort_col is not None:
            items.sort(key=_SORT_KEYS[self.sort_col], reverse=self.sort_desc)
        self.items = items

        for it in items:
            table.add_row(
                it.scope, it.label, str(it.message_count), it.hint or "—",
                it.status, it.current_leaf or (it.note and f"defer:{it.note}") or "—",
            )
        if items:
            table.move_cursor(row=min(max(prev, 0), len(items) - 1))
        self._update_coverage()

    def _headers(self) -> list[str]:
        out = []
        for i, name in enumerate(_COLS):
            mark = (" ▼" if self.sort_desc else " ▲") if i == self.sort_col else ""
            out.append(name + mark)
        return out

    def _update_coverage(self) -> None:
        cov = self.session.coverage()
        flag = "  ⚠ below 60% target" if cov.below_target else ""
        note = f"   filter: {self.search_text}" if self.search_text else ""
        self.query_one("#cov", Static).update(
            f"Projected coverage: {cov.covered}/{cov.total} "
            f"({cov.fraction * 100:.1f}%){flag}{note}"
        )

    def _current(self) -> QueueItem | None:
        if not self.items:
            return None
        idx = self.query_one("#grid", DataTable).cursor_row
        return self.items[idx] if 0 <= idx < len(self.items) else None

    # --- sorting (#20) --------------------------------------------------
    def sort_by(self, col: int) -> None:
        """Sort by a column; re-selecting the same column toggles direction."""
        if col == self.sort_col:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_col, self.sort_desc = col, False
        self.refresh_queue()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        self.sort_by(event.column_index)

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

    def action_search(self) -> None:
        self._open_input("search", "filter senders (substring); Esc to clear",
                         require_row=False, initial=self.search_text)

    def action_cancel_input(self) -> None:
        entry = self.query_one("#entry", Input)
        if not entry.has_class("on"):
            return
        entry.remove_class("on")
        was, self._mode = self._mode, None
        if was == "search":
            self.search_text = ""
            self.refresh_queue()
        self.query_one("#grid", DataTable).focus()

    def _open_input(self, mode: str, placeholder: str, require_row: bool = True,
                    initial: str = "") -> None:
        if require_row and self._current() is None:
            return
        self._mode = mode
        entry = self.query_one("#entry", Input)
        entry.placeholder = placeholder
        entry.value = initial
        entry.add_class("on")
        entry.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        entry = self.query_one("#entry", Input)
        entry.remove_class("on")
        mode, self._mode = self._mode, None
        grid = self.query_one("#grid", DataTable)
        if mode == "search":
            self.search_text = event.value.strip()
            self.refresh_queue()
            grid.focus()
            return
        it = self._current()
        if it is None or mode is None:
            grid.focus()
            return
        try:
            if mode == "override":
                self.session.set_rule(it.key, it.scope, event.value)
            elif mode == "defer":
                self.session.defer(it.key, it.scope, event.value)
        except LeafError as e:
            self._notify(str(e))
        grid.focus()
        self.refresh_queue()

    def _notify(self, msg: str) -> None:
        self.query_one("#cov", Static).update(f"⚠ {msg}")


def run_confirm(session: ConfirmSession, sender_filter: str | None = None) -> None:
    ConfirmApp(session, sender_filter=sender_filter).run()
