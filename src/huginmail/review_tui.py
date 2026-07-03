"""Textual TUI for `hugin review`. Walks LLM classifications worst-first; retag
individual messages (writes method='human'). Thin driver over ReviewSession."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import DataTable, Footer, Header, Input, Static

from .confirm import LeafError
from .review import ReviewItem, ReviewSession

_COLS = ("conf", "tag", "sender", "subject")


class ReviewApp(App):
    """Review low-confidence LLM calls: accept, retag, or make a sender rule."""

    CSS = """
    #grid { height: 1fr; }
    #detail { height: auto; padding: 0 1; color: $text-muted; }
    #bottom { dock: bottom; height: auto; }
    #entry { display: none; }
    #entry.on { display: block; }
    """
    BINDINGS = [
        ("a", "accept", "Accept"),
        ("o", "retag", "Retag"),
        ("r", "rule", "Retag+sender rule"),
        ("q", "quit", "Quit"),
        Binding("escape", "cancel_input", "Cancel", priority=True),
    ]

    def __init__(self, session: ReviewSession) -> None:
        super().__init__()
        self.session = session
        self.items: list[ReviewItem] = []
        self._mode: str | None = None  # 'retag' | 'rule'

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="grid", cursor_type="row")
        with Container(id="bottom"):
            yield Static("", id="detail")
            yield Static("", id="status")
            yield Input(id="entry", placeholder="")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#grid", DataTable).add_columns(*_COLS)
        self.refresh_items()

    # --- rendering ------------------------------------------------------
    def refresh_items(self) -> None:
        table = self.query_one("#grid", DataTable)
        prev = table.cursor_row
        table.clear()
        self.items = self.session.candidates()
        for it in self.items:
            table.add_row(f"{it.confidence:.2f}", it.tag, it.from_addr[:24],
                          it.subject[:50])
        if self.items:
            table.move_cursor(row=min(max(prev, 0), len(self.items) - 1))
        self._update_detail()

    def _current(self) -> ReviewItem | None:
        if not self.items:
            return None
        idx = self.query_one("#grid", DataTable).cursor_row
        return self.items[idx] if 0 <= idx < len(self.items) else None

    def _update_detail(self) -> None:
        it = self._current()
        status = self.query_one("#status", Static)
        detail = self.query_one("#detail", Static)
        if it is None:
            detail.update("")
            status.update("Nothing left to review 🎉")
            return
        detail.update(f"[b]{it.subject}[/b]\n{it.from_addr}  ·  "
                      f"tag=[b]{it.tag}[/b] ({it.confidence:.2f})\n"
                      f"rationale: {it.rationale}\n{it.snippet[:300]}")
        status.update(f"{len(self.items)} left to review "
                      f"(conf {self.session.min_conf}–{self.session.max_conf})")

    def on_data_table_row_highlighted(self, _e) -> None:
        self._update_detail()

    # --- actions --------------------------------------------------------
    def action_accept(self) -> None:
        """Keep the LLM tag; advance (no write)."""
        table = self.query_one("#grid", DataTable)
        if table.cursor_row + 1 < len(self.items):
            table.move_cursor(row=table.cursor_row + 1)
        self._update_detail()

    def action_retag(self) -> None:
        self._open_input("retag", "new tag or tag/subtag (e.g. newsletter)")

    def action_rule(self) -> None:
        self._open_input("rule", "tag for a sender rule on this address")

    def _open_input(self, mode: str, placeholder: str) -> None:
        if self._current() is None:
            return
        self._mode = mode
        entry = self.query_one("#entry", Input)
        entry.placeholder = placeholder
        entry.value = ""
        entry.add_class("on")
        entry.focus()

    def action_cancel_input(self) -> None:
        entry = self.query_one("#entry", Input)
        if entry.has_class("on"):
            entry.remove_class("on")
            self._mode = None
            self.query_one("#grid", DataTable).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        entry = self.query_one("#entry", Input)
        entry.remove_class("on")
        mode, self._mode = self._mode, None
        it = self._current()
        if it is not None and mode is not None:
            try:
                if mode == "retag":
                    self.session.retag(it, event.value)
                elif mode == "rule":
                    self.session.make_sender_rule(it.from_addr, event.value)
                    self.session.retag(it, event.value)
            except LeafError as e:
                self.query_one("#status", Static).update(f"⚠ {e}")
        self.query_one("#grid", DataTable).focus()
        self.refresh_items()  # retagged item drops out (no longer method='llm')


def run_review(session: ReviewSession) -> None:
    ReviewApp(session).run()
