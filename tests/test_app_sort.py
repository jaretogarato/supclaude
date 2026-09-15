import asyncio
import json
import os

from textual.widgets import DataTable

from supclaude.app import SupClaude, sort_sessions
from supclaude.iterm import ItermBridge
from supclaude.state import SessionState


def test_sort_needs_you_first_then_done_then_by_name():
    rows = [
        SessionState(session_id="1", name="b", state="idle"),
        SessionState(session_id="2", name="z", state="done"),
        SessionState(session_id="3", name="a", state="needs_you"),
        SessionState(session_id="4", name="c", state="working"),
        SessionState(session_id="5", name="a", state="done"),
    ]
    got = [s.session_id for s in sort_sessions(rows)]
    assert got == ["3", "5", "2", "4", "1"]


def test_unknown_state_renders_without_crashing(tmp_path, monkeypatch):
    """A state file with an unrecognized state must not tear down the app."""
    monkeypatch.setenv("SUPCLAUDE_HOME", str(tmp_path))
    # Keep the test hermetic: never open a real iTerm2 socket (and never import
    # the iterm2 package, which emits third-party DeprecationWarnings).
    async def no_connect(self) -> bool:
        return False

    monkeypatch.setattr(ItermBridge, "connect", no_connect)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "x.json").write_text(
        json.dumps(
            {
                "session_id": "x",
                "iterm_session_id": "",
                "cwd": "/x/Weird",
                "name": "Weird",
                "state": "bogus_state",
                "agents_running": 0,
                "last_prompt": "hi",
                "updated_at": "2026-09-14T10:00:00Z",
                "pid": os.getpid(),
            }
        )
    )

    async def run() -> list[str]:
        app = SupClaude()
        async with app.run_test() as pilot:
            await pilot.pause(1.0)
            table = app.query_one(DataTable)
            return [c.plain for c in table.get_row_at(0)] if table.row_count == 1 else []

    cells = asyncio.run(run())
    assert cells, "expected exactly one row"
    assert cells[2] == "BOGUS_STATE"
