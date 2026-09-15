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
        # source is one of startup/resume/clear/compact. Auto-compaction fires
        # mid-turn, so it must not reset the state or the agent count.
        if event.get("source") == "compact":
            return s
        return replace(s, state="idle", agents_running=0)

    if name == "UserPromptSubmit":
        # System-injected turns (<task-notification>, <system-reminder>, ...) also
        # fire this event; they still mean "working" but must not clobber the prompt.
        prompt = _one_line(event.get("prompt", ""))
        if prompt.startswith("<"):
            prompt = s.last_prompt
        return replace(s, state="working", last_prompt=prompt)

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
