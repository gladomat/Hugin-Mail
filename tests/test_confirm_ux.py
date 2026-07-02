from __future__ import annotations

import pytest
from textual.widgets import DataTable, Input

from huginmail.confirm import ConfirmSession
from huginmail.confirm_tui import ConfirmApp
from huginmail.report import senders_matching, top_senders
from huginmail.sync import RawMessage, sync_folder
from conftest import FakeImapSource, raw


def _seed_many(store, tax):
    """One dominant sender + a low-rank tail sender outside a top=1 queue."""
    msgs = [raw(i, f"m{i}", subject="hi", from_addr="bulk@shop.com")
            for i in range(1, 6)]
    msgs.append(raw(99, "tail", subject="hello", from_addr="rare@tail.org"))
    sync_folder(store, FakeImapSource({"INBOX": (10, msgs)}), tax, "INBOX")


# --- #19 sender filter (session/report level) --------------------------
def test_senders_matching_reaches_tail(store, tax):
    _seed_many(store, tax)
    top1 = {p.from_addr for p in top_senders(store, top=1)}
    assert "rare@tail.org" not in top1  # tail is outside top-1
    matched = {p.from_addr for p in senders_matching(store, "tail.org")}
    assert "rare@tail.org" in matched


def test_build_queue_filter_bypasses_top_n(store, tax):
    _seed_many(store, tax)
    s = ConfirmSession(store, tax, top=1)
    keys = {i.key for i in s.build_queue(sender_filter="rare@tail.org")}
    assert "rare@tail.org" in keys


# --- #20 sorting -------------------------------------------------------
@pytest.mark.asyncio
async def test_header_click_sorts_and_toggles(store, tax):
    _seed_many(store, tax)
    app = ConfirmApp(ConfirmSession(store, tax, top=100))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.sort_by(2)  # count ascending
        await pilot.pause()
        asc = [it.message_count for it in app.items]
        app.sort_by(2)  # toggle -> descending
        await pilot.pause()
        desc = [it.message_count for it in app.items]
    assert asc == sorted(asc) and desc == sorted(desc, reverse=True)


# --- #19 in-TUI search + #21 layout/esc --------------------------------
@pytest.mark.asyncio
async def test_search_filters_then_esc_clears(store, tax):
    _seed_many(store, tax)
    app = ConfirmApp(ConfirmSession(store, tax, top=100))
    async with app.run_test() as pilot:
        await pilot.pause()
        full = len(app.items)
        app.search_text = "tail"
        app.refresh_queue()
        await pilot.pause()
        assert 0 < len(app.items) < full
        assert all("tail" in it.label.lower() for it in app.items)
        # open search input then Esc clears the filter
        app._mode = "search"
        app.query_one("#entry", Input).add_class("on")
        app.action_cancel_input()
        await pilot.pause()
        assert app.search_text == "" and len(app.items) == full


@pytest.mark.asyncio
async def test_input_widget_within_screen(store, tax):
    _seed_many(store, tax)
    app = ConfirmApp(ConfirmSession(store, tax, top=100))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.action_override()
        await pilot.pause()
        entry = app.query_one("#entry", Input)
        assert entry.has_class("on")
        # docked bottom → within the 24-row screen, not pushed past it
        assert entry.region.bottom <= app.size.height
