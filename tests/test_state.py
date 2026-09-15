import pytest

from supclaude.state import SessionState, next_state

NOW = "2026-09-14T10:00:00Z"


def ev(name, **fields):
    d = {"session_id": "s1", "cwd": "/Users/x/Projects/Foo", "hook_event_name": name}
    d.update(fields)
    return d


def base(state="idle", agents=0, last_prompt=""):
    return SessionState(
        session_id="s1", state=state, agents_running=agents, last_prompt=last_prompt
    )


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


def test_session_start_compact_keeps_state_and_agent_count():
    """Auto-compaction fires SessionStart mid-turn; it must not reset anything."""
    s = next_state(base("working", 2), ev("SessionStart", source="compact"), NOW)
    assert s.state == "working"
    assert s.agents_running == 2
    assert s.updated_at == NOW


@pytest.mark.parametrize("source", ["startup", "resume", "clear"])
def test_session_start_other_sources_still_reset(source):
    s = next_state(base("working", 2), ev("SessionStart", source=source), NOW)
    assert s.state == "idle"
    assert s.agents_running == 0


@pytest.mark.parametrize(
    "prompt",
    [
        "<task-notification>agent finished</task-notification>",
        "<system-reminder>remember this</system-reminder>",
        "<command-message>compact is running</command-message>",
        "<local-command-stdout>out</local-command-stdout>",
    ],
)
def test_injected_prompt_keeps_last_prompt_but_still_goes_working(prompt):
    s = next_state(base("done", last_prompt="fix the bug"), ev("UserPromptSubmit", prompt=prompt), NOW)
    assert s.state == "working"
    assert s.last_prompt == "fix the bug"


def test_real_prompt_still_replaces_last_prompt():
    s = next_state(base("done", last_prompt="old"), ev("UserPromptSubmit", prompt="new thing"), NOW)
    assert s.state == "working"
    assert s.last_prompt == "new thing"
