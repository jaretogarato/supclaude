"""Textual dashboard: one row per Claude Code session."""

from __future__ import annotations

import datetime as dt

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Static

from supclaude import store
from supclaude.colors import COLORS, LABELS, SORT_ORDER
from supclaude.iterm import ItermBridge, uuid_from_env_id
from supclaude.state import SessionState

REFRESH_SECONDS = 0.5
BANNER_OK = "iTerm2 API: connected   keys: 1-9 jump   r refresh   q quit"
BANNER_OFF = (
    "iTerm2 API is OFF. Turn on: iTerm2 -> Settings -> General -> Magic -> Enable Python API. "
    "Rows still update; tab colors and jump keys need the API."
)


def _age(updated_at: str) -> str:
    try:
        t = dt.datetime.strptime(updated_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (ValueError, TypeError):
        return ""
    secs = int((dt.datetime.now(dt.timezone.utc) - t).total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    return f"{secs // 3600}h"


def sort_sessions(sessions: list[SessionState]) -> list[SessionState]:
    return sorted(sessions, key=lambda s: (SORT_ORDER.get(s.state, 99), s.name.lower(), s.session_id))


class SupClaude(App):
    CSS = """
    Screen { layout: vertical; }
    #banner { height: 1; padding: 0 1; }
    DataTable { height: 1fr; }
    """
    BINDINGS = [Binding("q", "quit", "Quit"), Binding("r", "refresh", "Refresh")] + [
        Binding(str(n), f"jump({n})", show=False) for n in range(1, 10)
    ]

    def __init__(self) -> None:
        super().__init__()
        self.bridge = ItermBridge()
        self.rows: list[SessionState] = []
        self._last_color: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Static(BANNER_OFF, id="banner")
        table = DataTable(cursor_type="row", zebra_stripes=True)
        table.add_columns("#", "session", "state", "agents", "last prompt", "age")
        yield table

    async def on_mount(self) -> None:
        ok = await self.bridge.connect()
        self.query_one("#banner", Static).update(BANNER_OK if ok else BANNER_OFF)
        if ok:
            self.run_worker(self.bridge.watch_focus(self._on_focus), exclusive=True, name="focus")
        self.set_interval(REFRESH_SECONDS, self.refresh_rows)
        await self.refresh_rows()

    async def _on_focus(self, uuid: str) -> None:
        for s in self.rows:
            if uuid_from_env_id(s.iterm_session_id) == uuid and s.state == "done":
                store.mark_seen(s.session_id)
        await self.refresh_rows()

    async def refresh_rows(self) -> None:
        sessions = sort_sessions(store.prune_dead())
        focused = self.bridge.focused_uuid
        if focused:
            for s in sessions:
                if s.state == "done" and uuid_from_env_id(s.iterm_session_id) == focused:
                    store.mark_seen(s.session_id)
                    s.state = "idle"
        self.rows = sessions
        self._render(sessions)
        await self._sync_colors(sessions)

    def _render(self, sessions: list[SessionState]) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for i, s in enumerate(sessions, start=1):
            color = COLORS.get(s.state, COLORS["idle"])
            table.add_row(
                Text(str(i) if i <= 9 else "", style="bold"),
                Text(s.name or s.session_id[:8], style=f"bold {color}"),
                Text(LABELS.get(s.state, str(s.state).upper()), style=f"bold {color}"),
                Text(str(s.agents_running) if s.agents_running else ""),
                Text(s.last_prompt, style="dim"),
                Text(_age(s.updated_at), style="dim"),
                key=s.session_id,
            )
        if not sessions:
            table.add_row("", "no Claude sessions yet", "", "", "", "")

    async def _sync_colors(self, sessions: list[SessionState]) -> None:
        if not self.bridge.connected:
            return
        seen: set[str] = set()
        for s in sessions:
            uuid = uuid_from_env_id(s.iterm_session_id)
            if not uuid:
                continue
            seen.add(uuid)
            color = COLORS.get(s.state, COLORS["idle"])
            if self._last_color.get(uuid) != color:
                await self.bridge.set_tab_color(uuid, color)
                self._last_color[uuid] = color
        for uuid in list(self._last_color):
            if uuid not in seen:
                await self.bridge.set_tab_color(uuid, None)
                self._last_color.pop(uuid, None)

    async def action_jump(self, n: int) -> None:
        if 1 <= n <= len(self.rows):
            await self.bridge.activate(uuid_from_env_id(self.rows[n - 1].iterm_session_id))

    async def action_refresh(self) -> None:
        await self.refresh_rows()

    async def action_quit(self) -> None:
        await self.bridge.clear_all_colors()
        self.exit()

    async def on_unmount(self) -> None:
        # Safety net for exits that never go through `q`. clear_all_colors only
        # touches tabs it has actually colored, so a second clear is a no-op.
        await self.bridge.clear_all_colors()


def run_dashboard() -> None:
    SupClaude().run()
