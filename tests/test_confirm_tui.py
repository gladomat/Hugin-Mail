from __future__ import annotations

import pytest

from textual.widgets import DataTable, Static

from huginmail.confirm import ConfirmSession
from huginmail.confirm_tui import ConfirmApp
from huginmail.sync import sync_folder
from conftest import FakeImapSource, raw


def _seed(store, tax):
    src = FakeImapSource({"INBOX": (10, [
        raw(1, "a", subject="SALE 50% off", from_addr="promo@shop.com"),
        raw(2, "b", subject="hi", from_addr="bob@friend.com"),
    ])})
    sync_folder(store, src, tax, "INBOX")


@pytest.mark.asyncio
async def test_tui_accept_writes_rule(store, tax):
    _seed(store, tax)
    session = ConfirmSession(store, tax, top=100, user="tester")
    app = ConfirmApp(session)
    async with app.run_test() as pilot:
        await pilot.pause()
        # move cursor to the promo@shop.com addr row (has a junk hint)
        idx = next(i for i, it in enumerate(app.items)
                   if it.scope == "addr" and it.key == "promo@shop.com")
        app.query_one("#grid", DataTable).move_cursor(row=idx)
        await pilot.press("a")
        await pilot.pause()
    assert any(r.key == "promo@shop.com" for r in store.get_rules())


@pytest.mark.asyncio
async def test_tui_populates_and_shows_coverage(store, tax):
    _seed(store, tax)
    session = ConfirmSession(store, tax, top=100)
    app = ConfirmApp(session)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert len(app.items) > 0
        cov_text = str(app.query_one("#cov", Static).render())
    assert "coverage" in cov_text.lower()
