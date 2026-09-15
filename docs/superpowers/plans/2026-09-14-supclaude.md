# SupClaude Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Textual dashboard in one iTerm2 window that shows the live state of every Claude Code session in other iTerm2 tabs, colors those tabs, and jumps to a session on a key press.

**Architecture:** A Claude Code hook script (`supclaude hook`) writes one JSON state file per session under `~/.supclaude/state/`. A Textual app polls that folder, talks to iTerm2 over its Python API (focus events, tab colors, activate tab), and renders one row per session. State transitions are a pure function so they are unit-tested without iTerm2 or Claude.

**Tech Stack:** Python 3.12+, `uv`, `textual` (8.x), `iterm2` (2.x), `pytest`. Packaged with `pyproject.toml`, installed with `uv tool install`.

**Spec:** `docs/superpowers/specs/2026-09-14-supclaude-design.md`

## Global Constraints

- Python `>=3.12`. Machine has 3.14.7 and `uv 0.12.6`.
- All colors come from `supclaude/colors.py`. No other file contains a hex code.
- State names (internal): `working`, `needs_you`, `done`, `agents`, `idle`.
- State file dir: `~/.supclaude/state/`. Override with env `SUPCLAUDE_HOME` (tests use a tmp dir).
- The hook must always exit 0 and must never print to stdout (stdout goes back to Claude).
- Hook events registered: `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PermissionRequest`, `Notification`, `SubagentStart`, `SubagentStop`, `Stop`, `SessionEnd`.
- `ITERM_SESSION_ID` looks like `w0t10p0:04548B7D-A59D-4843-9D79-2CDF425BAC70`. The iTerm2 API session id is the part after the colon.
- Git commits end with:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01S1QimT6KwA1D963ESJQmwq
  ```
- Run tests with `uv run pytest -q` from the repo root.

## File Structure

```
pyproject.toml              package metadata, deps, entry point
supclaude/__init__.py       version string
supclaude/colors.py         Color Authority: hex per state, labels, sort order, hex_to_rgb
supclaude/state.py          SessionState dataclass + next_state() pure function
supclaude/store.py          read/write/delete state files, atomic writes, dead-pid prune
supclaude/hook.py           stdin hook JSON -> store (Claude runs this)
supclaude/install.py        merge/unmerge hook entries in ~/.claude/settings.json
supclaude/iterm.py          iTerm2 bridge: connect, focus, activate, tab color
supclaude/app.py            Textual dashboard
supclaude/cli.py            `supclaude` entry point: hook | install | uninstall | (run)
tests/test_colors.py
tests/test_state.py
tests/test_store.py
tests/test_hook.py
tests/test_install.py
README.md
```

---

### Task 1: Project scaffold + Color Authority

**Files:**
- Create: `pyproject.toml`, `supclaude/__init__.py`, `supclaude/colors.py`, `tests/test_colors.py`, `.gitignore`

**Interfaces:**
- Produces: `colors.STATES: tuple[str,...]`, `colors.COLORS: dict[str,str]`, `colors.LABELS: dict[str,str]`, `colors.SORT_ORDER: dict[str,int]`, `colors.hex_to_rgb(hex: str) -> tuple[int,int,int]`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "supclaude"
version = "0.1.0"
description = "Dashboard for Claude Code sessions running in iTerm2 tabs"
requires-python = ">=3.12"
dependencies = [
    "textual>=8.0",
    "iterm2>=2.0",
]

[project.scripts]
supclaude = "supclaude.cli:main"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["supclaude"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `supclaude/__init__.py` and `.gitignore`**

`supclaude/__init__.py`:
```python
__version__ = "0.1.0"
```

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
dist/
.pytest_cache/
```

- [ ] **Step 3: Write the failing test `tests/test_colors.py`**

```python
import re

from supclaude import colors

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def test_every_state_has_color_label_and_sort():
    assert colors.STATES == ("working", "needs_you", "done", "agents", "idle")
    for s in colors.STATES:
        assert HEX.match(colors.COLORS[s]), s
        assert colors.LABELS[s]
        assert s in colors.SORT_ORDER


def test_waiting_is_hot_pink():
    assert colors.COLORS["needs_you"].upper() == "#FF69B4"


def test_sort_order_puts_needs_you_first_and_idle_last():
    order = sorted(colors.STATES, key=lambda s: colors.SORT_ORDER[s])
    assert order[0] == "needs_you"
    assert order[-1] == "idle"


def test_hex_to_rgb():
    assert colors.hex_to_rgb("#FF69B4") == (255, 105, 180)
    assert colors.hex_to_rgb("3b82f6") == (59, 130, 246)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/test_colors.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'supclaude.colors'` (uv will create `.venv` and install deps first).

- [ ] **Step 5: Write `supclaude/colors.py`**

```python
"""Color Authority. Every color in SupClaude comes from here.

Change a hex value here and both the dashboard and the iTerm2 tab colors follow.
"""

STATES = ("working", "needs_you", "done", "agents", "idle")

COLORS = {
    "working": "#3B82F6",    # blue
    "needs_you": "#FF69B4",  # hot pink
    "done": "#22C55E",       # green
    "agents": "#EAB308",     # yellow
    "idle": "#6B7280",       # gray
}

LABELS = {
    "working": "WORKING",
    "needs_you": "NEEDS YOU",
    "done": "DONE",
    "agents": "AGENTS",
    "idle": "IDLE",
}

# Lower number sorts higher in the dashboard.
SORT_ORDER = {
    "needs_you": 0,
    "done": 1,
    "working": 2,
    "agents": 3,
    "idle": 4,
}


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_colors.py -q`
Expected: `4 passed`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock .gitignore supclaude/__init__.py supclaude/colors.py tests/test_colors.py
git commit -m "feat: scaffold package and Color Authority"
```

---

### Task 2: State model and transition rules

**Files:**
- Create: `supclaude/state.py`, `tests/test_state.py`

**Interfaces:**
- Consumes: `colors.STATES`
- Produces:
  - `@dataclass SessionState(session_id: str, iterm_session_id: str = "", cwd: str = "", name: str = "", state: str = "idle", agents_running: int = 0, last_prompt: str = "", updated_at: str = "", pid: int = 0)`
  - `SessionState.to_dict() -> dict`, `SessionState.from_dict(d: dict) -> SessionState`
  - `next_state(current: SessionState, event: dict, now: str) -> SessionState | None` (None means delete the session)
  - `NEEDS_YOU_NOTIFICATIONS: frozenset[str]`

- [ ] **Step 1: Write the failing test `tests/test_state.py`**

```python
from dataclasses import replace

import pytest

from supclaude.state import SessionState, next_state

NOW = "2026-09-14T10:00:00Z"


def ev(name, **fields):
    d = {"session_id": "s1", "cwd": "/Users/x/Projects/Foo", "hook_event_name": name}
    d.update(fields)
    return d


def base(state="idle", agents=0):
    return SessionState(session_id="s1", state=state, agents_running=agents)


def test_session_start_resets_to_idle_and_fills_name():
    s = next_state(base("working", 2), ev("SessionStart"), NOW)
    assert s.state == "idle"
    assert s.agents_running == 0
    assert s.cwd == "/Users/x/Projects/Foo"
    assert s.name == "Foo"
    assert s.updated_at == NOW


def test_prompt_submit_is_working_and_stores_short_prompt():
    s = next_state(base(), ev("UserPromptSubmit", prompt="x" * 200), NOW)
    assert s.state == "working"
    assert s.last_prompt == "x" * 80


def test_ask_user_question_is_needs_you():
    s = next_state(base("working"), ev("PreToolUse", tool_name="AskUserQuestion"), NOW)
    assert s.state == "needs_you"


def test_other_tool_use_keeps_working():
    s = next_state(base("working"), ev("PreToolUse", tool_name="Bash"), NOW)
    assert s.state == "working"


def test_permission_request_is_needs_you():
    s = next_state(base("working"), ev("PermissionRequest", tool_name="Bash"), NOW)
    assert s.state == "needs_you"


@pytest.mark.parametrize("kind", ["permission_prompt", "agent_needs_input", "elicitation_dialog"])
def test_needs_you_notifications(kind):
    s = next_state(base("working"), ev("Notification", notification_type=kind), NOW)
    assert s.state == "needs_you"


def test_idle_prompt_notification_does_not_change_state():
    s = next_state(base("done"), ev("Notification", notification_type="idle_prompt"), NOW)
    assert s.state == "done"


def test_post_tool_use_after_needs_you_is_working():
    s = next_state(base("needs_you"), ev("PostToolUse", tool_name="AskUserQuestion"), NOW)
    assert s.state == "working"


def test_post_tool_use_while_working_stays_working():
    s = next_state(base("working"), ev("PostToolUse", tool_name="Bash"), NOW)
    assert s.state == "working"


def test_subagent_start_and_stop_count():
    s = next_state(base("working"), ev("SubagentStart"), NOW)
    assert s.agents_running == 1
    s = next_state(s, ev("SubagentStop"), NOW)
    assert s.agents_running == 0
    s = next_state(s, ev("SubagentStop"), NOW)
    assert s.agents_running == 0  # never below zero


def test_stop_with_agents_is_agents_else_done():
    assert next_state(base("working", 1), ev("Stop"), NOW).state == "agents"
    assert next_state(base("working", 0), ev("Stop"), NOW).state == "done"


def test_last_agent_stop_while_resting_becomes_done():
    s = next_state(base("agents", 1), ev("SubagentStop"), NOW)
    assert s.state == "done"
    assert s.agents_running == 0


def test_session_end_returns_none():
    assert next_state(base(), ev("SessionEnd"), NOW) is None


def test_unknown_event_only_touches_timestamp():
    s = next_state(base("working"), ev("PreCompact"), NOW)
    assert s.state == "working"
    assert s.updated_at == NOW


def test_roundtrip_dict():
    s = SessionState(session_id="s1", iterm_session_id="w0t1p0:ABC", cwd="/a/b", name="b",
                     state="done", agents_running=0, last_prompt="hi", updated_at=NOW, pid=42)
    assert SessionState.from_dict(s.to_dict()) == s


def test_from_dict_ignores_unknown_keys():
    s = SessionState.from_dict({"session_id": "s1", "bogus": 1})
    assert s.session_id == "s1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_state.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'supclaude.state'`

- [ ] **Step 3: Write `supclaude/state.py`**

```python
"""Session state model and the pure transition function."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, fields, replace

PROMPT_MAX = 80

NEEDS_YOU_NOTIFICATIONS = frozenset(
    {"permission_prompt", "agent_needs_input", "elicitation_dialog"}
)


@dataclass
class SessionState:
    session_id: str
    iterm_session_id: str = ""
    cwd: str = ""
    name: str = ""
    state: str = "idle"
    agents_running: int = 0
    last_prompt: str = ""
    updated_at: str = ""
    pid: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SessionState":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


def _one_line(text: str) -> str:
    return " ".join(str(text).split())[:PROMPT_MAX]


def next_state(current: SessionState, event: dict, now: str) -> SessionState | None:
    """Return the new state for a hook event, or None when the session ended."""
    name = event.get("hook_event_name", "")
    if name == "SessionEnd":
        return None

    cwd = event.get("cwd") or current.cwd
    s = replace(
        current,
        cwd=cwd,
        name=os.path.basename(cwd.rstrip("/")) or current.name,
        updated_at=now,
    )

    if name == "SessionStart":
        return replace(s, state="idle", agents_running=0)

    if name == "UserPromptSubmit":
        return replace(s, state="working", last_prompt=_one_line(event.get("prompt", "")))

    if name == "PreToolUse":
        if event.get("tool_name") == "AskUserQuestion":
            return replace(s, state="needs_you")
        return s

    if name == "PermissionRequest":
        return replace(s, state="needs_you")

    if name == "Notification":
        if event.get("notification_type") in NEEDS_YOU_NOTIFICATIONS:
            return replace(s, state="needs_you")
        return s

    if name == "PostToolUse":
        if s.state == "needs_you":
            return replace(s, state="working")
        return s

    if name == "SubagentStart":
        return replace(s, agents_running=s.agents_running + 1)

    if name == "SubagentStop":
        n = max(0, s.agents_running - 1)
        state = "done" if (s.state == "agents" and n == 0) else s.state
        return replace(s, agents_running=n, state=state)

    if name == "Stop":
        return replace(s, state="agents" if s.agents_running > 0 else "done")

    return s
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_state.py -q`
Expected: `18 passed`

- [ ] **Step 5: Commit**

```bash
git add supclaude/state.py tests/test_state.py
git commit -m "feat: session state model and transition rules"
```

---

### Task 3: State store (files on disk)

**Files:**
- Create: `supclaude/store.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `SessionState` from Task 2
- Produces:
  - `store.home() -> Path` (from `SUPCLAUDE_HOME` env or `~/.supclaude`)
  - `store.state_dir() -> Path` (creates it)
  - `store.path_for(session_id: str) -> Path`
  - `store.load(session_id: str) -> SessionState | None`
  - `store.save(state: SessionState) -> None` (atomic)
  - `store.delete(session_id: str) -> None`
  - `store.load_all() -> list[SessionState]` (skips bad files)
  - `store.pid_alive(pid: int) -> bool`
  - `store.prune_dead() -> list[SessionState]` (deletes files whose pid is dead, returns the live ones)
  - `store.mark_seen(session_id: str) -> None` (a `done` session becomes `idle`)

- [ ] **Step 1: Write the failing test `tests/test_store.py`**

```python
import json
import os

import pytest

from supclaude import store
from supclaude.state import SessionState


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPCLAUDE_HOME", str(tmp_path))
    return tmp_path


def test_state_dir_is_created_under_home(home):
    d = store.state_dir()
    assert d == home / "state"
    assert d.is_dir()


def test_save_load_delete_roundtrip():
    s = SessionState(session_id="abc", state="working", pid=os.getpid())
    store.save(s)
    assert store.path_for("abc").exists()
    assert store.load("abc") == s
    store.delete("abc")
    assert store.load("abc") is None
    store.delete("abc")  # deleting twice does not raise


def test_save_leaves_no_temp_files():
    store.save(SessionState(session_id="abc"))
    names = [p.name for p in store.state_dir().iterdir()]
    assert names == ["abc.json"]


def test_load_all_skips_bad_files():
    store.save(SessionState(session_id="good", pid=os.getpid()))
    (store.state_dir() / "bad.json").write_text("{not json")
    (store.state_dir() / "empty.json").write_text("")
    got = store.load_all()
    assert [s.session_id for s in got] == ["good"]


def test_pid_alive():
    assert store.pid_alive(os.getpid())
    assert not store.pid_alive(2_000_000_000)
    assert not store.pid_alive(0)


def test_prune_dead_removes_dead_sessions():
    store.save(SessionState(session_id="live", pid=os.getpid()))
    store.save(SessionState(session_id="dead", pid=2_000_000_000))
    live = store.prune_dead()
    assert [s.session_id for s in live] == ["live"]
    assert not store.path_for("dead").exists()


def test_mark_seen_turns_done_into_idle_only():
    store.save(SessionState(session_id="d", state="done"))
    store.save(SessionState(session_id="w", state="working"))
    store.mark_seen("d")
    store.mark_seen("w")
    store.mark_seen("missing")
    assert store.load("d").state == "idle"
    assert store.load("w").state == "working"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'supclaude.store'`

- [ ] **Step 3: Write `supclaude/store.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_store.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add supclaude/store.py tests/test_store.py
git commit -m "feat: on-disk session store with atomic writes"
```

---

### Task 4: Hook entry point

**Files:**
- Create: `supclaude/hook.py`, `tests/test_hook.py`

**Interfaces:**
- Consumes: `next_state`, `SessionState`, `store.load/save/delete/home`
- Produces:
  - `hook.run(stdin_text: str, env: dict, now: str | None = None, pid: int | None = None) -> None`
  - `hook.find_claude_pid() -> int`
  - `hook.main() -> None` (reads stdin, never raises, exits 0)

- [ ] **Step 1: Write the failing test `tests/test_hook.py`**

```python
import json
import os

import pytest

from supclaude import hook, store

NOW = "2026-09-14T10:00:00Z"
ENV = {"ITERM_SESSION_ID": "w0t1p0:ABC-123"}


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPCLAUDE_HOME", str(tmp_path))
    return tmp_path


def payload(name, **fields):
    d = {"session_id": "s1", "cwd": "/tmp/Proj", "hook_event_name": name}
    d.update(fields)
    return json.dumps(d)


def test_first_event_creates_file_with_iterm_id_and_pid():
    hook.run(payload("SessionStart"), ENV, now=NOW, pid=4242)
    s = store.load("s1")
    assert s.iterm_session_id == "w0t1p0:ABC-123"
    assert s.pid == 4242
    assert s.name == "Proj"
    assert s.state == "idle"
    assert s.updated_at == NOW


def test_events_chain_through_existing_file():
    hook.run(payload("SessionStart"), ENV, now=NOW, pid=1)
    hook.run(payload("UserPromptSubmit", prompt="do it"), ENV, now=NOW, pid=1)
    assert store.load("s1").state == "working"
    hook.run(payload("Stop"), ENV, now=NOW, pid=1)
    assert store.load("s1").state == "done"


def test_session_end_deletes_file():
    hook.run(payload("SessionStart"), ENV, now=NOW, pid=1)
    hook.run(payload("SessionEnd"), ENV, now=NOW, pid=1)
    assert store.load("s1") is None


def test_bad_input_does_not_raise_and_logs():
    hook.run("{nope", ENV, now=NOW, pid=1)
    hook.run("", ENV, now=NOW, pid=1)
    hook.run(json.dumps({"no_session": 1}), ENV, now=NOW, pid=1)
    assert store.load_all() == []
    log = store.home() / "hook.log"
    assert log.exists()


def test_missing_iterm_env_is_ok():
    hook.run(payload("SessionStart"), {}, now=NOW, pid=1)
    assert store.load("s1").iterm_session_id == ""


def test_find_claude_pid_returns_positive_int():
    assert hook.find_claude_pid() > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_hook.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'supclaude.hook'`

- [ ] **Step 3: Write `supclaude/hook.py`**

```python
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

from supclaude import store
from supclaude.state import SessionState, next_state

MAX_PARENT_WALK = 8


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(msg: str) -> None:
    try:
        with open(store.home() / "hook.log", "a") as f:
            f.write(f"{_now()} {msg}\n")
    except OSError:
        pass


def find_claude_pid() -> int:
    """Walk up the parent chain and return the first pid whose command mentions claude.

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
        if "claude" in command.lower():
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
        current = store.load(session_id) or SessionState(session_id=session_id)
        if not current.iterm_session_id:
            current.iterm_session_id = env.get("ITERM_SESSION_ID", "")
        if not current.pid:
            current.pid = pid if pid is not None else find_claude_pid()
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_hook.py -q`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add supclaude/hook.py tests/test_hook.py
git commit -m "feat: hook entry point writes session state"
```

---

### Task 5: Installer for settings.json + CLI skeleton

**Files:**
- Create: `supclaude/install.py`, `supclaude/cli.py`, `tests/test_install.py`

**Interfaces:**
- Consumes: nothing from earlier tasks except `hook.main`
- Produces:
  - `install.HOOK_EVENTS: tuple[str,...]`
  - `install.install(settings_path: Path, command: str) -> None`
  - `install.uninstall(settings_path: Path, command: str) -> None`
  - `install.default_settings_path() -> Path` (`~/.claude/settings.json`)
  - `install.hook_command() -> str` (absolute path of the `supclaude` executable + ` hook`)
  - `cli.main() -> None` with sub-commands `hook`, `install`, `uninstall`; no sub-command runs the dashboard (`app.run_dashboard`, added in Task 7)

- [ ] **Step 1: Write the failing test `tests/test_install.py`**

```python
import json

from supclaude import install

CMD = "/opt/bin/supclaude hook"


def read(p):
    return json.loads(p.read_text())


def test_install_creates_file_and_all_events(tmp_path):
    p = tmp_path / "settings.json"
    install.install(p, CMD)
    d = read(p)
    for ev in install.HOOK_EVENTS:
        entries = d["hooks"][ev]
        assert entries == [{"hooks": [{"type": "command", "command": CMD}]}]


def test_install_keeps_existing_keys_and_hooks(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "statusLine": {"type": "command", "command": "foo"},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]},
    }))
    install.install(p, CMD)
    d = read(p)
    assert d["statusLine"]["command"] == "foo"
    stop = d["hooks"]["Stop"]
    assert stop[0]["hooks"][0]["command"] == "other"
    assert stop[1]["hooks"][0]["command"] == CMD


def test_install_twice_is_idempotent(tmp_path):
    p = tmp_path / "settings.json"
    install.install(p, CMD)
    install.install(p, CMD)
    d = read(p)
    assert len(d["hooks"]["Stop"]) == 1


def test_uninstall_removes_only_ours(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]},
    }))
    install.install(p, CMD)
    install.uninstall(p, CMD)
    d = read(p)
    assert d["hooks"]["Stop"] == [{"hooks": [{"type": "command", "command": "other"}]}]
    assert "SessionStart" not in d["hooks"]


def test_uninstall_on_missing_file_is_ok(tmp_path):
    install.uninstall(tmp_path / "nope.json", CMD)


def test_hook_command_is_absolute_and_ends_with_hook():
    cmd = install.hook_command()
    assert cmd.endswith(" hook")
    assert cmd.startswith("/")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_install.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'supclaude.install'`

- [ ] **Step 3: Write `supclaude/install.py`**

```python
"""Add or remove SupClaude hook entries in ~/.claude/settings.json."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HOOK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PermissionRequest",
    "Notification",
    "SubagentStart",
    "SubagentStop",
    "Stop",
    "SessionEnd",
)


def default_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def hook_command() -> str:
    exe = shutil.which("supclaude") or sys.argv[0]
    return f"{Path(exe).resolve()} hook"


def _entry(command: str) -> dict:
    return {"hooks": [{"type": "command", "command": command}]}


def _is_ours(entry: dict, command: str) -> bool:
    return any(h.get("command") == command for h in entry.get("hooks", []))


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text().strip()
    return json.loads(text) if text else {}


def _dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def install(settings_path: Path, command: str) -> None:
    data = _load(settings_path)
    hooks = data.setdefault("hooks", {})
    for ev in HOOK_EVENTS:
        entries = hooks.setdefault(ev, [])
        if not any(_is_ours(e, command) for e in entries):
            entries.append(_entry(command))
    _dump(settings_path, data)


def uninstall(settings_path: Path, command: str) -> None:
    if not settings_path.exists():
        return
    data = _load(settings_path)
    hooks = data.get("hooks", {})
    for ev in list(hooks):
        kept = [e for e in hooks[ev] if not _is_ours(e, command)]
        if kept:
            hooks[ev] = kept
        else:
            del hooks[ev]
    _dump(settings_path, data)
```

- [ ] **Step 4: Write `supclaude/cli.py`**

```python
"""`supclaude` command line entry point."""

from __future__ import annotations

import argparse
import sys

from supclaude import install as installer

REMINDER = (
    "Reminder: turn on the iTerm2 Python API:\n"
    "  iTerm2 -> Settings -> General -> Magic -> Enable Python API"
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="supclaude", description="Claude Code session dashboard for iTerm2")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("hook", help="(used by Claude Code) read a hook event from stdin")
    sub.add_parser("install", help="add hooks to ~/.claude/settings.json")
    sub.add_parser("uninstall", help="remove hooks from ~/.claude/settings.json")
    args = parser.parse_args(argv)

    if args.cmd == "hook":
        from supclaude.hook import main as hook_main
        hook_main()
        return

    if args.cmd == "install":
        cmd = installer.hook_command()
        installer.install(installer.default_settings_path(), cmd)
        print(f"Installed hooks -> {installer.default_settings_path()}")
        print(f"Hook command: {cmd}")
        print(REMINDER)
        return

    if args.cmd == "uninstall":
        installer.uninstall(installer.default_settings_path(), installer.hook_command())
        print("Removed SupClaude hooks.")
        return

    from supclaude.app import run_dashboard
    run_dashboard()


if __name__ == "__main__":
    main(sys.argv[1:])
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest -q`
Expected: all pass (`test_install.py` gives `6 passed`; earlier files still pass).

- [ ] **Step 6: Smoke-test the hook through the CLI**

Run:
```bash
SUPCLAUDE_HOME=/tmp/sc-smoke ITERM_SESSION_ID=w0t0p0:TEST echo '{"session_id":"smoke","cwd":"/tmp/X","hook_event_name":"UserPromptSubmit","prompt":"hello"}' | uv run supclaude hook; echo "exit=$?"; cat /tmp/sc-smoke/state/smoke.json; echo; rm -rf /tmp/sc-smoke
```
Expected: `exit=0`, JSON with `"state": "working"`, `"last_prompt": "hello"`, `"iterm_session_id": "w0t0p0:TEST"`. No other stdout.

- [ ] **Step 7: Commit**

```bash
git add supclaude/install.py supclaude/cli.py tests/test_install.py
git commit -m "feat: settings.json installer and CLI"
```

---

### Task 6: iTerm2 bridge

**Files:**
- Create: `supclaude/iterm.py`

No unit tests (needs a live iTerm2). Hand-tested in Task 8.

**Interfaces:**
- Consumes: `colors.hex_to_rgb`
- Produces:
  - `iterm.uuid_from_env_id(iterm_session_id: str) -> str`
  - `class ItermBridge`:
    - `connected: bool`
    - `focused_uuid: str | None` (kept fresh by `watch_focus`)
    - `async connect() -> bool`
    - `async activate(uuid: str) -> None`
    - `async set_tab_color(uuid: str, hex_color: str | None) -> None` (None restores "no tab color")
    - `async watch_focus(on_change) -> None` (long-running; calls `on_change(uuid)` on each focus change)
    - `async clear_all_colors() -> None`

- [ ] **Step 1: Write `supclaude/iterm.py`**

```python
"""Thin bridge to the iTerm2 Python API.

Everything here is best-effort: if iTerm2's API is off, `connect()` returns False
and the other calls do nothing.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from supclaude.colors import hex_to_rgb


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
        except Exception:
            self.connected = False
        return self.connected

    def _session(self, uuid: str):
        if not self.connected or not uuid:
            return None
        try:
            return self._app.get_session_by_id(uuid)
        except Exception:
            return None

    async def activate(self, uuid: str) -> None:
        s = self._session(uuid)
        if s is None:
            return
        try:
            await s.async_activate(select_tab=True, order_window_front=True)
        except Exception:
            pass

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
        except Exception:
            pass

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
                    result = on_change(changed.session_id)
                    if asyncio.iscoroutine(result):
                        await result
        except asyncio.CancelledError:
            raise
        except Exception:
            self.connected = False
```

- [ ] **Step 2: Import check**

Run: `uv run python -c "from supclaude.iterm import ItermBridge, uuid_from_env_id; print(uuid_from_env_id('w0t1p0:ABC'))"`
Expected: `ABC`

- [ ] **Step 3: Commit**

```bash
git add supclaude/iterm.py
git commit -m "feat: iTerm2 bridge for focus, activate, tab color"
```

---

### Task 7: Textual dashboard

**Files:**
- Create: `supclaude/app.py`

**Interfaces:**
- Consumes: `store.prune_dead`, `store.mark_seen`, `colors.*`, `ItermBridge`, `uuid_from_env_id`, `SessionState`
- Produces: `app.run_dashboard() -> None`

Behavior:
- Every 0.5 s: `store.prune_dead()`, sort by `SORT_ORDER` then by name, redraw the table, sync tab colors (only send a color when it changed), and if the focused tab belongs to a `done` session call `store.mark_seen`.
- Keys `1`–`9` activate that row's tab. `q` quits and clears tab colors. `r` forces a refresh.
- Banner at the top says "iTerm2 API: connected" or the enable-API reminder.

- [ ] **Step 1: Write `supclaude/app.py`**

```python
"""Textual dashboard: one row per Claude Code session."""

from __future__ import annotations

import asyncio
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
    except ValueError:
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
        self._last_color: dict[str, str | None] = {}

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
            color = COLORS[s.state]
            table.add_row(
                Text(str(i) if i <= 9 else "", style="bold"),
                Text(s.name or s.session_id[:8], style=f"bold {color}"),
                Text(LABELS[s.state], style=f"bold {color}"),
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
            color = COLORS[s.state]
            if self._last_color.get(uuid) != color:
                await self.bridge.set_tab_color(uuid, color)
                self._last_color[uuid] = color
        for uuid in list(self._last_color):
            if uuid not in seen:
                await self.bridge.set_tab_color(uuid, None)
                del self._last_color[uuid]

    async def action_jump(self, n: int) -> None:
        if 1 <= n <= len(self.rows):
            await self.bridge.activate(uuid_from_env_id(self.rows[n - 1].iterm_session_id))

    async def action_refresh(self) -> None:
        await self.refresh_rows()

    async def action_quit(self) -> None:
        await self.bridge.clear_all_colors()
        self.exit()


def run_dashboard() -> None:
    SupClaude().run()
```

- [ ] **Step 2: Add a small unit test for sorting to `tests/test_app_sort.py`**

```python
from supclaude.app import sort_sessions
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
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 4: Smoke-run the dashboard against fake state files (no iTerm2 needed)**

Run:
```bash
mkdir -p /tmp/sc-demo/state
cat > /tmp/sc-demo/state/a.json <<EOF
{"session_id":"a","iterm_session_id":"","cwd":"/x/Alpha","name":"Alpha","state":"needs_you","agents_running":0,"last_prompt":"pick one","updated_at":"2026-09-14T10:00:00Z","pid":$$}
EOF
cat > /tmp/sc-demo/state/b.json <<EOF
{"session_id":"b","iterm_session_id":"","cwd":"/x/Beta","name":"Beta","state":"working","agents_running":2,"last_prompt":"refactor","updated_at":"2026-09-14T10:00:00Z","pid":$$}
EOF
SUPCLAUDE_HOME=/tmp/sc-demo uv run supclaude
```
Expected: two rows. Alpha first in hot pink `NEEDS YOU`, Beta in blue `WORKING` with `2` agents. Press `q` to exit. Then `rm -rf /tmp/sc-demo`.

- [ ] **Step 5: Commit**

```bash
git add supclaude/app.py tests/test_app_sort.py
git commit -m "feat: Textual dashboard with tab colors and jump keys"
```

---

### Task 8: Install for real, hand-test with iTerm2, README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Install the tool**

Run: `uv tool install --editable /Users/jaredgallardo/Projects/SupClaude && which supclaude`
Expected: a path like `/Users/jaredgallardo/.local/bin/supclaude`.

- [ ] **Step 2: Install the hooks**

Run: `supclaude install`
Expected: prints the settings path, the absolute hook command, and the API reminder. Then `python3 -c "import json;print(list(json.load(open('$HOME/.claude/settings.json'))['hooks']))"` lists the 10 events.

- [ ] **Step 3: Verify iTerm2 API is on**

Run: `uv run python -c "
import iterm2
async def m(c):
    app = await iterm2.async_get_app(c)
    print('focused', app.current_terminal_window.current_tab.current_session.session_id)
iterm2.run_until_complete(m)"`
Expected: prints a UUID. If it fails, turn on iTerm2 → Settings → General → Magic → Enable Python API and retry.

- [ ] **Step 4: Hand test**

1. Open a new small iTerm2 window. Run `supclaude`. Banner says `iTerm2 API: connected`.
2. In another tab start `claude`. Within a second a row appears as `IDLE` (gray). The tab turns gray.
3. Send a prompt. Row and tab turn blue `WORKING`.
4. Wait for the answer. Row turns green `DONE`.
5. Click that tab. Row turns gray `IDLE`.
6. Ask Claude something that triggers a permission prompt (e.g. `run: rm -i /tmp/nothing`). Row turns hot pink `NEEDS YOU`. Answer it. Row goes blue then green.
7. In the dashboard press `1`. iTerm2 focuses that tab.
8. Quit `claude`. Row disappears. Press `q` in the dashboard. Tab colors clear.

Write down anything that did not work in `docs/superpowers/plans/2026-09-14-supclaude.md` under a "Hand test notes" heading at the bottom.

- [ ] **Step 5: Write `README.md`**

```markdown
# SupClaude

A tiny iTerm2 window that shows the state of every Claude Code session in your other tabs. It colors those tabs too.

## States

| Word | Color | Meaning |
|---|---|---|
| WORKING | blue | Claude is on a task |
| NEEDS YOU | hot pink | Claude asked a question or needs a permission |
| DONE | green | Claude finished and you have not looked yet |
| AGENTS | yellow | Claude is resting, background agents still run |
| IDLE | gray | Resting, nothing new |

Colors live in `supclaude/colors.py`. Change them there.

## Install

```bash
uv tool install --editable .
supclaude install
```

Turn on the iTerm2 API: iTerm2 → Settings → General → Magic → Enable Python API.

## Run

```bash
supclaude
```

Keys: `1`–`9` jump to that session's tab. `r` refresh. `q` quit.

## Uninstall

```bash
supclaude uninstall
uv tool uninstall supclaude
```

## How it works

Claude Code hooks call `supclaude hook` on each event. That writes `~/.supclaude/state/<session>.json`. The dashboard polls that folder and talks to iTerm2 over its Python API for focus, tab colors, and jumping.
```

- [ ] **Step 6: Commit**

```bash
git add README.md docs/superpowers/plans/2026-09-14-supclaude.md
git commit -m "docs: README and hand-test notes"
```
