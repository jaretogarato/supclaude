"""Add or remove SupClaude hook entries in ~/.claude/settings.json."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

BACKUP_SUFFIX = ".bak-supclaude"

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


def _is_our_command(command: str) -> bool:
    """Ours when the executable is named `supclaude` and the last argument is `hook`.

    Matching structurally (not on the exact string) lets a venv install and a uv
    tool install recognize each other, so uninstall never leaves a dead entry.
    """
    argv = str(command or "").split()
    return len(argv) >= 2 and Path(argv[0]).name == "supclaude" and argv[-1] == "hook"


def _is_ours(entry: dict) -> bool:
    return any(_is_our_command(h.get("command", "")) for h in entry.get("hooks", []))


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text().strip()
    return json.loads(text) if text else {}


def _dump(path: Path, data: dict) -> None:
    """Write atomically so a crash mid-write cannot truncate settings.json."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-supclaude-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(data, indent=2) + "\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _backup_once(path: Path) -> None:
    bak = path.with_name(path.name + BACKUP_SUFFIX)
    if path.exists() and not bak.exists():
        shutil.copy2(path, bak)


def install(settings_path: Path, command: str) -> None:
    data = _load(settings_path)
    _backup_once(settings_path)
    hooks = data.setdefault("hooks", {})
    for ev in HOOK_EVENTS:
        # Drop any entry of ours (possibly from another install path) and add one.
        entries = [e for e in hooks.get(ev, []) if not _is_ours(e)]
        entries.append(_entry(command))
        hooks[ev] = entries
    _dump(settings_path, data)


def uninstall(settings_path: Path, command: str | None = None) -> None:
    """Remove every SupClaude hook entry. `command` is accepted but not used:
    entries are recognized structurally, whatever path they were installed from."""
    if not settings_path.exists():
        return
    data = _load(settings_path)
    hooks = data.get("hooks", {})
    removed = False
    for ev in list(hooks):
        kept = [e for e in hooks[ev] if not _is_ours(e)]
        if len(kept) == len(hooks[ev]):
            continue
        removed = True
        if kept:
            hooks[ev] = kept
        else:
            del hooks[ev]
    if not removed:
        return
    if not hooks:
        data.pop("hooks", None)
    _dump(settings_path, data)
