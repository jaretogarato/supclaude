"""Thin bridge to the iTerm2 Python API.

Everything here is best-effort: if iTerm2's API is off, `connect()` returns False
and the other calls do nothing.
"""

from __future__ import annotations

import asyncio
import os
from typing import Awaitable, Callable

from supclaude import store
from supclaude.colors import hex_to_rgb


def _log(msg: str) -> None:
    """Append to ~/.supclaude/dashboard.log, but only when SUPCLAUDE_DEBUG is set."""
    if not os.environ.get("SUPCLAUDE_DEBUG"):
        return
    try:
        home = store.home()
        home.mkdir(parents=True, exist_ok=True)
        with open(home / "dashboard.log", "a") as f:
            f.write(f"{msg}\n")
    except OSError:
        pass


def uuid_from_env_id(iterm_session_id: str) -> str:
    """'w0t10p0:04548B7D-...' -> '04548B7D-...'."""
    return iterm_session_id.rsplit(":", 1)[-1]


class ItermBridge:
    def __init__(self) -> None:
        self.connected = False
        self.focused_uuid: str | None = None
        self._connection = None
        self._app = None
        self._colored: set[str] = set()

    async def connect(self) -> bool:
        try:
            import iterm2  # imported lazily so tests never touch it
            self._connection = await iterm2.Connection.async_create()
            self._app = await iterm2.async_get_app(self._connection)
            win = self._app.current_terminal_window
            if win and win.current_tab and win.current_tab.current_session:
                self.focused_uuid = win.current_tab.current_session.session_id
            self.connected = True
        except Exception as e:
            _log(f"connect: {e!r}")
            self.connected = False
        return self.connected

    def _session(self, uuid: str):
        if not self.connected or not uuid:
            return None
        try:
            return self._app.get_session_by_id(uuid)
        except Exception as e:
            _log(f"_session: {e!r}")
            return None

    async def activate(self, uuid: str) -> None:
        s = self._session(uuid)
        if s is None:
            return
        try:
            await s.async_activate(select_tab=True, order_window_front=True)
        except Exception as e:
            _log(f"activate: {e!r}")

    async def set_tab_color(self, uuid: str, hex_color: str | None) -> None:
        s = self._session(uuid)
        if s is None:
            return
        try:
            import iterm2
            p = iterm2.LocalWriteOnlyProfile()
            if hex_color:
                r, g, b = hex_to_rgb(hex_color)
                p.set_use_tab_color(True)
                p.set_tab_color(iterm2.Color(r, g, b))
                self._colored.add(uuid)
            else:
                p.set_use_tab_color(False)
                self._colored.discard(uuid)
            await s.async_set_profile_properties(p)
        except Exception as e:
            _log(f"set_tab_color: {e!r}")

    async def clear_all_colors(self) -> None:
        for uuid in list(self._colored):
            await self.set_tab_color(uuid, None)

    async def watch_focus(self, on_change: Callable[[str], Awaitable[None] | None]) -> None:
        if not self.connected:
            return
        try:
            import iterm2
            async with iterm2.FocusMonitor(self._connection) as mon:
                while True:
                    update = await mon.async_get_next_update()
                    changed = update.active_session_changed
                    if changed is None:
                        continue
                    self.focused_uuid = changed.session_id
                    try:
                        result = on_change(changed.session_id)
                        if asyncio.iscoroutine(result):
                            await result
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        _log(f"watch_focus/on_change: {e!r}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _log(f"watch_focus: {e!r}")
            self.connected = False
