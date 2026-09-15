"""One JSON file per Claude session under ~/.supclaude/state/."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from supclaude.state import SessionState


def home() -> Path:
    return Path(os.environ.get("SUPCLAUDE_HOME") or Path.home() / ".supclaude")


def state_dir() -> Path:
    d = home() / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def path_for(session_id: str) -> Path:
    return state_dir() / f"{session_id}.json"


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
    try:
        path_for(session_id).unlink()
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


def prune_dead() -> list[SessionState]:
    live = []
    for s in load_all():
        if pid_alive(s.pid):
            live.append(s)
        else:
            delete(s.session_id)
    return live


def mark_seen(session_id: str) -> None:
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
