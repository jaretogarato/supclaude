"""One JSON file per Claude session under ~/.supclaude/state/."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Iterator

from supclaude.state import SessionState


def home() -> Path:
    return Path(os.environ.get("SUPCLAUDE_HOME") or Path.home() / ".supclaude")


def state_dir() -> Path:
    d = home() / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def path_for(session_id: str) -> Path:
    return state_dir() / f"{session_id}.json"


def carry_dir() -> Path:
    d = home() / "carry"
    d.mkdir(parents=True, exist_ok=True)
    return d


def carry_path_for(pid: int) -> Path:
    return carry_dir() / f"{pid}.json"


def lock_path_for(session_id: str) -> Path:
    return state_dir() / f"{session_id}.lock"


@contextmanager
def locked(session_id: str) -> Iterator[None]:
    """Hold an exclusive per-session advisory lock for the block.

    Claude Code runs several `supclaude hook` processes at the same instant
    (e.g. SubagentStart and PostToolUse for the Agent tool), so every
    read-modify-write of a session file must happen under this lock or the
    later writer clobbers the earlier one with stale data.
    """
    fd = os.open(lock_path_for(session_id), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def load(session_id: str) -> SessionState | None:
    return _read(path_for(session_id))


def save(state: SessionState) -> None:
    target = path_for(state.session_id)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=state_dir())
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state.to_dict(), f)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def delete(session_id: str) -> None:
    for p in (path_for(session_id), lock_path_for(session_id)):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def load_all() -> list[SessionState]:
    out = []
    for p in sorted(state_dir().glob("*.json")):
        s = _read(p)
        if s is not None:
            out.append(s)
    return out


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def carry_save(pid: int, model: str) -> None:
    """Stash a dying session's model under its pid for the next session on it.

    `/clear` ends the session and immediately starts a new one in the same
    process, so the pid is the only thing the two share. Called from the live
    hook: it must never raise.
    """
    if pid <= 0 or not model:
        return
    try:
        carry_path_for(pid).write_text(json.dumps({"model": model}))
    except (OSError, TypeError, ValueError):
        pass


def carry_take(pid: int) -> str:
    """The model of the previous session on this pid, "" when there is none.

    A still-live state file with the same pid wins: SessionEnd for the old
    session and SessionStart for the new one take different per-session locks,
    so they run in either order, and when SessionStart wins the stash is never
    taken and keeps a model that may since have changed. Two states sharing a
    pid can only be one tab's pre- and post-clear session, so the match is safe.
    The stash is always removed, consumed or not. Never raises.
    """
    if pid <= 0:
        return ""
    try:
        p = carry_path_for(pid)
        stashed = None
        try:
            d = json.loads(p.read_text())
            if isinstance(d, dict):
                stashed = d.get("model")
        except (OSError, ValueError, TypeError):
            pass
        try:
            p.unlink()
        except OSError:
            pass
        for s in load_all():
            if s.pid == pid and s.model:
                return s.model
        return stashed if isinstance(stashed, str) and stashed else ""
    except Exception:
        return ""


def prune_dead() -> list[SessionState]:
    live = []
    for s in load_all():
        if pid_alive(s.pid):
            live.append(s)
        else:
            delete(s.session_id)
    _prune_carry()
    return live


def _prune_carry() -> None:
    """Drop carry files whose process is gone (the tab closed instead of /clear)."""
    try:
        files = list(carry_dir().glob("*.json"))
    except OSError:
        return
    for p in files:
        try:
            pid = int(p.stem)
        except ValueError:
            continue  # not a pid file: leave it alone
        if not pid_alive(pid):
            try:
                p.unlink()
            except OSError:
                pass


def mark_seen(session_id: str) -> None:
    with locked(session_id):
        s = load(session_id)
        if s is not None and s.state == "done":
            save(replace(s, state="idle"))


def _read(p: Path) -> SessionState | None:
    try:
        d = json.loads(p.read_text())
        if not isinstance(d, dict) or "session_id" not in d:
            return None
        return SessionState.from_dict(d)
    except (OSError, ValueError, TypeError):
        return None
