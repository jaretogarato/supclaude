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
from dataclasses import replace
from pathlib import Path

from supclaude import store
from supclaude.state import SessionState, next_state
from supclaude.transcript import (
    read_last_up_next,
    read_last_usage,
    short_model,
    up_next_from_text,
)

MAX_PARENT_WALK = 8

# Events whose transcript_path is the top-level session's file and that land
# after an assistant turn wrote its usage. Subagent tool events carry agent_id
# and point at the subagent's own transcript, so they are excluded.
TRANSCRIPT_EVENTS = frozenset({"Stop", "PostToolUse", "UserPromptSubmit"})


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


def _with_up_next(state: SessionState, event: dict, path: str | None) -> SessionState:
    """Fill up_next on a top-level Stop, preferring the event's own final reply.

    Claude Code runs Stop hooks concurrently with its transcript flush, so the
    reply that just ended the turn is often not in the JSONL yet. The Stop event
    carries it in `last_assistant_message`, so that field decides when present:
    a reply with no marker genuinely has no next step and clears up_next. Only
    when the field is missing (older Claude Code) or not a string do we fall
    back to the transcript tail, where a None result leaves up_next unchanged
    rather than blanking a good value on a racy read.
    """
    message = event.get("last_assistant_message")
    if isinstance(message, str) and message:
        return replace(state, up_next=up_next_from_text(message) or "")
    if not path:
        return state
    up_next = read_last_up_next(path)
    return replace(state, up_next=up_next) if up_next is not None else state


def _with_usage(state: SessionState, event: dict) -> SessionState:
    """Fill model/context_tokens from the transcript and, on Stop, up_next.

    On any problem return state as is. This runs inside the live hook on every
    turn, so it must never raise or slow the hook down: both readers only touch
    the file's tail. up_next is read only on the top-level Stop because mid-turn
    the transcript still holds the previous reply's line.
    """
    try:
        name = event.get("hook_event_name")
        if name not in TRANSCRIPT_EVENTS or event.get("agent_id"):
            return state
        path = event.get("transcript_path")
        if path:
            found = read_last_usage(path)
            if found is not None:
                model, ctx = found
                state = replace(state, model=short_model(model), context_tokens=ctx)
        if name == "Stop":
            state = _with_up_next(state, event, path)
        return state
    except Exception:
        return state


def _model_from_event(event: dict) -> str:
    """The short display name in the event's own `model` field, "" when absent.

    SessionStart may carry the model on some Claude Code versions (2.1.273 does
    not), as a plain string or as a dict with an "id" key.
    """
    m = event.get("model")
    if isinstance(m, dict):
        m = m.get("id")
    if not isinstance(m, str) or not m:
        return ""
    return short_model(m)


def _restore_model_on_clear(state: SessionState, event: dict) -> SessionState:
    """After `/clear`, give the new session the model of the tab's previous one.

    `/clear` ends the session and starts a new one in the same process, so the
    old state file (and its model) is gone and the new transcript holds no reply
    yet. The event's own model wins when a version supplies it; otherwise take
    what SessionEnd stashed under the pid, which is already a short name. Never
    raises: this runs inside the live hook.
    """
    try:
        if event.get("hook_event_name") != "SessionStart" or event.get("source") != "clear":
            return state
        if state.model:
            return state
        model = _model_from_event(event) or store.carry_take(state.pid)
        return replace(state, model=model) if model else state
    except Exception:
        return state


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
                # A `/clear` ends this session and starts a new one in the same
                # process: hand the model to it before the file goes away.
                store.carry_save(current.pid, current.model)
                store.delete(session_id)
            else:
                store.save(_restore_model_on_clear(_with_usage(new, event), event))
    except Exception:
        _log(traceback.format_exc())


def main() -> None:
    try:
        run(sys.stdin.read(), dict(os.environ))
    except Exception:
        _log(traceback.format_exc())
    sys.exit(0)
