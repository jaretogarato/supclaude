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


def seed(home, session_id: str, *, state: str = "idle", iterm: str = "", **extra) -> None:
    (home / "state" / f"{session_id}.json").write_text(
        json.dumps(
            {
                **extra,
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


def test_model_and_ctx_columns_render(home):
    seed(home, "a", model="fable-5.1", context_tokens=160203)

    async def run():
        app = SupClaude()
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            table = app.query_one(DataTable)
            assert [str(c.label) for c in table.columns.values()] == [
                "#", "session", "state", "agents", "model", "ctx", "last prompt", "age", "up next"
            ]
            return [c.plain for c in table.get_row_at(0)]

    cells = asyncio.run(run())
    assert cells[4] == "fable-5.1"
    assert cells[5] == "160k"


def test_up_next_column_renders_text(home):
    seed(home, "a", state="needs_you", up_next="run the tests")

    async def run():
        app = SupClaude()
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            table = app.query_one(DataTable)
            cells = [c.plain for c in table.get_row_at(0)]
            # Line 0 is the header; line 1 is row 0. A needs_you row paints the
            # up-next text in the state color so it stands out.
            segs = [s for s in table.render_line(1) if s.text.strip() in ("run", "the", "tests", "run the tests")]
            assert segs, "up next cell text not found on row 0"
            colors = {s.style.color.triplet for s in segs if s.style and s.style.color}
            return cells, colors

    cells, colors = asyncio.run(run())
    assert cells[8] == "run the tests"
    assert cells[6] == "hi"
    assert colors == {hex_to_rgb(COLORS["needs_you"])}


def test_up_next_column_empty_when_unset(home):
    seed(home, "a", up_next="")

    async def run():
        app = SupClaude()
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            table = app.query_one(DataTable)
            return [c.plain for c in table.get_row_at(0)]

    cells = asyncio.run(run())
    assert cells[8] == ""
    assert cells[6] == "hi"


def test_placeholder_row_has_one_cell_per_column(home):
    async def run():
        app = SupClaude()
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            table = app.query_one(DataTable)
            return len(table.columns), len(table.get_row_at(0))

    assert asyncio.run(run()) == (9, 9)


def test_ctx_cell_color_follows_token_range(home):
    """The ctx cell is colored by token count (independent of the state color)."""
    seed(home, "a", context_tokens=160_203)  # 150k-200k band -> #E87543
    seed(home, "b", context_tokens=30_000)  # under 50k -> #4CAF50

    def cell_colors(table: DataTable, line: int, text: str) -> set[tuple[int, int, int]]:
        segs = [s for s in table.render_line(line) if s.text.strip() == text]
        assert segs, f"{text!r} not found on line {line}"
        return {s.style.color.triplet for s in segs if s.style and s.style.color}

    async def run():
        app = SupClaude()
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            table = app.query_one(DataTable)
            assert [c.plain for c in table.get_row_at(0)][5] == "160k"
            assert [c.plain for c in table.get_row_at(1)][5] == "30k"
            # Line 0 is the header; line 1 is row 0 ("a"), line 2 is row 1 ("b").
            return cell_colors(table, 1, "160k"), cell_colors(table, 2, "30k")

    big, small = asyncio.run(run())
    assert big == {(232, 117, 67)}
    assert small == {(76, 175, 80)}


def _stub_tab_titles(monkeypatch, titles: dict[str, str]) -> None:
    """Make the bridge report these {uuid: tab title} pairs without touching iTerm2."""

    async def fake_tab_titles(self, uuids: set[str]) -> dict[str, str]:
        return {u: t for u, t in titles.items() if u in uuids}

    monkeypatch.setattr(ItermBridge, "tab_titles", fake_tab_titles)


def _session_cells(home) -> list[str]:
    async def run():
        app = SupClaude()
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            table = app.query_one(DataTable)
            return [[c.plain for c in table.get_row_at(i)][1] for i in range(table.row_count)]

    return asyncio.run(run())


def test_session_cell_uses_iterm_tab_title(home, monkeypatch):
    """The tab name the user gave beats the folder name, which drifts when Claude cds."""
    _stub_tab_titles(monkeypatch, {"ABC-123": "shopthefrequency"})
    seed(home, "a", iterm="w0t1p0:ABC-123")

    assert _session_cells(home) == ["shopthefrequency"]


def test_session_cell_falls_back_to_name_when_tab_untitled(home, monkeypatch):
    """A session missing from the title map keeps SessionState.name."""
    _stub_tab_titles(monkeypatch, {"ABC-123": "named tab"})
    seed(home, "a", iterm="w0t1p0:ABC-123")
    seed(home, "b", iterm="w0t2p0:DEF-456")

    assert _session_cells(home) == ["named tab", "b"]


def test_session_cell_keeps_name_when_no_tab_titles(home, monkeypatch):
    """Disconnected bridge: every row stays on the folder name."""
    _stub_tab_titles(monkeypatch, {})
    seed(home, "a", iterm="w0t1p0:ABC-123")
    seed(home, "b")

    assert _session_cells(home) == ["a", "b"]


def test_tab_titles_on_disconnected_bridge_is_empty():
    assert asyncio.run(ItermBridge().tab_titles({"ABC-123"})) == {}
