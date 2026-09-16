"""Session state model and the pure transition function."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field, fields, replace

PROMPT_MAX = 80

NEEDS_YOU_NOTIFICATIONS = frozenset(
    {"permission_prompt", "agent_needs_input", "elicitation_dialog"}
)

ANON_PREFIX = "anon-"


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
    # Ids of subagents currently running; agents_running is always len(agent_ids).
    # Kept as a separate field because the dashboard reads agents_running directly.
    agent_ids: list[str] = field(default_factory=list)
    # Read from the session transcript on each turn (see transcript.py). model is
    # the short display name; context_tokens is what the model saw last turn.
    model: str = ""
    context_tokens: int = 0
    # The reply's trailing "UP NEXT: ..." line (prefix stripped); cleared on each new prompt.
    up_next: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SessionState":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


def _one_line(text: str) -> str:
    return " ".join(str(text).split())[:PROMPT_MAX]


def _with_agents(s: SessionState, ids: list[str], **extra) -> SessionState:
    return replace(s, agent_ids=list(ids), agents_running=len(ids), **extra)


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
        agent_ids=list(current.agent_ids),
    )

    if name == "SessionStart":
        # source is one of startup/resume/clear/compact. Auto-compaction fires
        # mid-turn, so it must not reset the state or the agent count.
        if event.get("source") == "compact":
            return s
        return _with_agents(s, [], state="idle")

    if name == "UserPromptSubmit":
        # System-injected turns (<task-notification>, <system-reminder>, ...) also
        # fire this event; they still mean "working" but must not clobber the prompt.
        prompt = _one_line(event.get("prompt", ""))
        if prompt.startswith("<"):
            prompt = s.last_prompt
        return replace(s, state="working", last_prompt=prompt, up_next="")

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
        # Older Claude Code sends no agent_id; count those with synthetic ids.
        agent_id = event.get("agent_id") or f"{ANON_PREFIX}{len(s.agent_ids) + 1}"
        ids = s.agent_ids if agent_id in s.agent_ids else s.agent_ids + [agent_id]
        return _with_agents(s, ids)

    if name == "SubagentStop":
        # A stop for an id we never saw start (observed in real traces) must not
        # steal a real agent's count. Anonymous stops only pop anonymous starts.
        agent_id = event.get("agent_id")
        if not agent_id:
            anon = [i for i in s.agent_ids if i.startswith(ANON_PREFIX)]
            agent_id = anon[-1] if anon else None
        if agent_id is None or agent_id not in s.agent_ids:
            return s
        ids = [i for i in s.agent_ids if i != agent_id]
        state = "done" if (s.state == "agents" and not ids) else s.state
        return _with_agents(s, ids, state=state)

    if name == "Stop":
        return replace(s, state="agents" if s.agents_running > 0 else "done")

    return s
