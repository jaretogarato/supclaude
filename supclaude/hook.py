"""Claude Code hook entry point. Reads hook JSON on stdin, updates the state file.

Rules: never print to stdout, never raise, always exit 0.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

from supclaude import store
from supclaude.state import SessionState, next_state

MAX_PARENT_WALK = 8


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(msg: str) -> None:
    try:
        home = store.home()
        home.mkdir(parents=True, exist_ok=True)
        with open(home / "hook.log", "a") as f:
            f.write(f"{_now()} {msg}\n")
    except OSError:
        pass


def find_claude_pid() -> int:
    """Walk up the parent chain and return the first pid running the `claude` binary.

    A command matches when its executable basename is exactly "claude" (the
    common case), or when "claude" is one of the executable path's directory
    components (e.g. launchers like happy run
    `~/.local/share/claude/versions/2.1.223 ...`). A plain substring match
    would also hit transient shells like `zsh -c source
    ~/.claude/shell-snapshots/...` (component ".claude", not "claude"), whose
    pid dies immediately and makes prune_dead drop the session.

    Falls back to the direct parent pid.
    """
    pid = os.getppid()
    fallback = pid
    for _ in range(MAX_PARENT_WALK):
        if pid <= 1:
            break
        try:
            out = subprocess.run(
                ["ps", "-o", "ppid=,command=", "-p", str(pid)],
                capture_output=True, text=True, timeout=2,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            break
        if not out:
            break
        ppid_str, _, command = out.partition(" ")
        argv = command.split()
        if argv:
            exe = Path(argv[0])
            if exe.name == "claude" or "claude" in exe.parts:
                return pid
        try:
            pid = int(ppid_str)
        except ValueError:
            break
    return fallback


def run(stdin_text: str, env: dict, now: str | None = None, pid: int | None = None) -> None:
    now = now or _now()
    try:
        event = json.loads(stdin_text or "{}")
        session_id = event.get("session_id") if isinstance(event, dict) else None
        if not session_id:
            _log(f"ignored: no session_id in {stdin_text[:200]!r}")
            return
        # Several hook processes for one session fire at the same instant
        # (SubagentStart + PostToolUse for the Agent tool), so the whole
        # load -> next_state -> save must run under the per-session lock.
        with store.locked(session_id):
            current = store.load(session_id) or SessionState(session_id=session_id)
            # `claude --resume` reuses the session id from a new process and often a
            # new tab, so SessionStart always re-reads both; other events only fill
            # blanks.
            is_start = event.get("hook_event_name") == "SessionStart"
            if is_start or not current.iterm_session_id:
                current.iterm_session_id = env.get("ITERM_SESSION_ID", "")
            if is_start or not current.pid:
                current.pid = pid if pid is not None else find_claude_pid()
            if os.environ.get("SUPCLAUDE_TRACE") or (store.home() / "trace").exists():
                _log(f"event {event.get('hook_event_name')} source={event.get('source')!r} "
                     f"tool={event.get('tool_name')!r} sid={session_id[:8]} "
                     f"agent={event.get('agent_id')!r} -> was {current.state}/{current.agents_running}")
            new = next_state(current, event, now)
            if new is None:
                store.delete(session_id)
            else:
                store.save(new)
    except Exception:
        _log(traceback.format_exc())


def main() -> None:
    try:
        run(sys.stdin.read(), dict(os.environ))
    except Exception:
        _log(traceback.format_exc())
    sys.exit(0)
