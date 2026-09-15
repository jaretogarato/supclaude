"""Cursor behaviour of the dashboard table: colors, refresh stability, enter/double-click jump."""

import asyncio
import json
import os

import pytest
from rich.style import Style
from textual import events
from textual.widgets import DataTable
from textual.widgets.data_table import RowKey

from supclaude.app import BANNER_OK, SupClaude
from supclaude.colors import COLORS, hex_to_rgb
from supclaude.iterm import ItermBridge, uuid_from_env_id


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Hermetic SUPCLAUDE_HOME with a stubbed iTerm2 bridge (never opens a socket)."""
    monkeypatch.setenv("SUPCLAUDE_HOME", str(tmp_path))

    async def no_connect(self) -> bool:
        return False

    monkeypatch.setattr(ItermBridge, "connect", no_connect)
    (tmp_path / "state").mkdir()
    return tmp_path


def seed(home, session_id: str, *, state: str = "idle", iterm: str = "") -> None:
    (home / "state" / f"{session_id}.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "iterm_session_id": iterm,
                "cwd": f"/x/{session_id}",
                "name": session_id,
                "state": state,
                "agents_running": 0,
                "last_prompt": "hi",
                "updated_at": "2026-09-14T10:00:00Z",
                "pid": os.getpid(),
            }
        )
    )


def test_cursor_row_keeps_cell_colors(home):
    """The row cursor must not repaint the per-cell foreground (green DONE, pink NEEDS YOU)."""
    seed(home, "a", state="needs_you")

    async def run():
        app = SupClaude()
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            table = app.query_one(DataTable)
            table.move_cursor(row=0, animate=False)
            await pilot.pause(0.1)
            assert table.cursor_row == 0
            # Line 0 is the header; line 1 is row 0, which is under the cursor.
            segs = [s for s in table.render_line(1) if s.text.strip() in ("NEEDS", "YOU", "NEEDS YOU")]
            assert segs, "state cell text not found on the cursor row"
            return {s.style.color.triplet for s in segs if s.style and s.style.color}

    colors = asyncio.run(run())
    assert colors == {hex_to_rgb(COLORS["needs_you"])}


def test_cursor_css_sets_only_background(home):
    """Our overrides must never add a color rule of their own (partial = this node only)."""
    seed(home, "a", state="done")

    async def run():
        app = SupClaude()
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            table = app.query_one(DataTable)
            hover = table.get_component_rich_style("datatable--hover", partial=True)
            return table.cursor_foreground_priority, hover.color, hover.bgcolor

    priority, hover_color, hover_bg = asyncio.run(run())
    assert priority == "renderable"
    assert hover_color is None
    assert hover_bg is not None


def test_refresh_keeps_cursor_row(home):
    seed(home, "a")
    seed(home, "b")

    async def run():
        app = SupClaude()
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            table = app.query_one(DataTable)
            assert table.row_count == 2
            table.move_cursor(row=1, animate=False)
            await app.refresh_rows()
            await pilot.pause(0.1)
            return table.cursor_row

    assert asyncio.run(run()) == 1


def test_refresh_clamps_cursor_when_row_vanishes(home):
    seed(home, "a")
    seed(home, "b")

    async def run():
        app = SupClaude()
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            table = app.query_one(DataTable)
            table.move_cursor(row=1, animate=False)
            (home / "state" / "b.json").unlink()
            await app.refresh_rows()
            await pilot.pause(0.1)
            return table.row_count, table.cursor_row

    assert asyncio.run(run()) == (1, 0)


def test_enter_on_row_activates_tab(home, monkeypatch):
    calls: list[str] = []

    async def fake_activate(self, uuid: str) -> None:
        calls.append(uuid)

    monkeypatch.setattr(ItermBridge, "activate", fake_activate)
    seed(home, "a", state="done", iterm="w0t0p0:ABCD-1234")

    async def run():
        app = SupClaude()
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            table = app.query_one(DataTable)
            await app.on_data_table_row_selected(DataTable.RowSelected(table, 0, RowKey("a")))
            # Unknown key (e.g. the placeholder row) is ignored, not an error.
            await app.on_data_table_row_selected(DataTable.RowSelected(table, 0, RowKey("nope")))

    asyncio.run(run())
    assert calls == [uuid_from_env_id("w0t0p0:ABCD-1234")]
    assert calls == ["ABCD-1234"]


def _click(table: DataTable, row: int, *, chain: int = 1) -> events.Click:
    """A synthetic Click carrying the cell meta the DataTable renderer attaches."""
    return events.Click(
        table,
        x=1,
        y=row + 1,
        delta_x=0,
        delta_y=0,
        button=1,
        shift=False,
        meta=False,
        ctrl=False,
        style=Style(meta={"row": row, "column": 0}),
        chain=chain,
    )


@pytest.fixture
def activate_calls(monkeypatch) -> list[str]:
    calls: list[str] = []

    async def fake_activate(self, uuid: str) -> None:
        calls.append(uuid)

    monkeypatch.setattr(ItermBridge, "activate", fake_activate)
    return calls


def test_single_click_moves_cursor_without_jump(home, activate_calls):
    seed(home, "a", iterm="w0t0p0:AAAA-0000")
    seed(home, "b", iterm="w0t0p0:BBBB-0000")

    async def run():
        app = SupClaude()
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            table = app.query_one(DataTable)
            assert table.cursor_row == 0
            await table._on_click(_click(table, 1))
            await pilot.pause()
            return table.cursor_row

    assert asyncio.run(run()) == 1
    assert activate_calls == []


def test_single_click_on_cursor_row_does_not_jump(home, activate_calls):
    """Stock Textual posts RowSelected when the clicked cell is already the cursor; we must not."""
    seed(home, "a", iterm="w0t0p0:AAAA-0000")
    seed(home, "b", iterm="w0t0p0:BBBB-0000")

    async def run():
        app = SupClaude()
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            table = app.query_one(DataTable)
            await table._on_click(_click(table, 1))
            await pilot.pause()
            assert table.cursor_row == 1
            await table._on_click(_click(table, 1))
            await pilot.pause()
            return table.cursor_row

    assert asyncio.run(run()) == 1
    assert activate_calls == []


def test_double_click_jumps_to_row_session(home, activate_calls):
    seed(home, "a", iterm="w0t0p0:AAAA-0000")
    seed(home, "b", iterm="w0t0p0:BBBB-0000")

    async def run():
        app = SupClaude()
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            table = app.query_one(DataTable)
            await table._on_click(_click(table, 1, chain=2))
            await pilot.pause()
            return table.cursor_row

    assert asyncio.run(run()) == 1
    assert activate_calls == [uuid_from_env_id("w0t0p0:BBBB-0000")]


def test_banner_mentions_enter_and_double_click():
    assert BANNER_OK == (
        "iTerm2 API: connected   keys: 1-9, enter, or double-click jump   r refresh   q quit"
    )
