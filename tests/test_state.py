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
    s = next_state(base("agents"), ev("SubagentStart"), NOW)
    s = next_state(s, ev("SubagentStop"), NOW)
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


# --- agent id tracking (phantom SubagentStop must not steal a real agent's count) ---


def test_subagent_stop_for_unknown_id_is_ignored():
    s = next_state(base("working"), ev("SubagentStart", agent_id="real"), NOW)
    s = next_state(s, ev("Stop"), NOW)
    assert s.state == "agents"
    assert s.agents_running == 1
    s = next_state(s, ev("SubagentStop", agent_id="phantom"), NOW)
    assert s.state == "agents"
    assert s.agents_running == 1
    assert s.agent_ids == ["real"]
    assert s.updated_at == NOW


def test_duplicate_subagent_start_of_same_id_counts_once():
    s = next_state(base("working"), ev("SubagentStart", agent_id="a1"), NOW)
    s = next_state(s, ev("SubagentStart", agent_id="a1"), NOW)
    assert s.agents_running == 1
    assert s.agent_ids == ["a1"]


def test_known_id_stop_removes_that_agent_only():
    s = next_state(base("working"), ev("SubagentStart", agent_id="a1"), NOW)
    s = next_state(s, ev("SubagentStart", agent_id="a2"), NOW)
    assert s.agents_running == 2
    s = next_state(s, ev("SubagentStop", agent_id="a1"), NOW)
    assert s.agents_running == 1
    assert s.agent_ids == ["a2"]


def test_subagent_start_and_stop_without_agent_id_use_anon_ids():
    s = next_state(base("working"), ev("SubagentStart"), NOW)
    assert s.agent_ids == ["anon-1"]
    s = next_state(s, ev("SubagentStart"), NOW)
    assert s.agent_ids == ["anon-1", "anon-2"]
    assert s.agents_running == 2
    s = next_state(s, ev("SubagentStop"), NOW)
    assert s.agent_ids == ["anon-1"]
    assert s.agents_running == 1
    s = next_state(s, ev("SubagentStop"), NOW)
    assert s.agent_ids == []
    assert s.agents_running == 0


def test_anonymous_stop_does_not_remove_a_named_agent():
    s = next_state(base("working"), ev("SubagentStart", agent_id="a1"), NOW)
    s = next_state(s, ev("SubagentStop"), NOW)
    assert s.agent_ids == ["a1"]
    assert s.agents_running == 1


def test_session_start_clears_agent_ids():
    s = next_state(base("working"), ev("SubagentStart", agent_id="a1"), NOW)
    s = next_state(s, ev("SessionStart", source="startup"), NOW)
    assert s.agent_ids == []
    assert s.agents_running == 0


def test_session_start_compact_keeps_agent_ids():
    s = next_state(base("working"), ev("SubagentStart", agent_id="a1"), NOW)
    s = next_state(s, ev("SessionStart", source="compact"), NOW)
    assert s.agent_ids == ["a1"]
    assert s.agents_running == 1


def test_last_named_agent_stop_while_resting_becomes_done():
    s = next_state(base("working"), ev("SubagentStart", agent_id="a1"), NOW)
    s = next_state(s, ev("Stop"), NOW)
    assert s.state == "agents"
    s = next_state(s, ev("SubagentStop", agent_id="a1"), NOW)
    assert s.state == "done"
    assert s.agents_running == 0


def test_from_dict_without_agent_ids_gives_empty_list():
    s = SessionState.from_dict({"session_id": "s1", "agents_running": 1})
    assert s.agent_ids == []


def test_roundtrip_dict_with_agent_ids():
    s = SessionState(session_id="s1", agents_running=2, agent_ids=["a1", "a2"])
    d = s.to_dict()
    assert d["agent_ids"] == ["a1", "a2"]
    assert SessionState.from_dict(d) == s


def test_default_agent_ids_are_not_shared_between_instances():
    a = SessionState(session_id="a")
    b = SessionState(session_id="b")
    a.agent_ids.append("x")
    assert b.agent_ids == []


def test_model_and_context_fields_default_and_survive_old_files():
    old = {"session_id": "s1", "state": "idle", "agents_running": 0}
    s = SessionState.from_dict(old)
    assert s.model == ""
    assert s.context_tokens == 0


def test_next_state_carries_model_and_context_through():
    s = SessionState(session_id="s1", model="fable-5.1", context_tokens=160203)
    for name in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SubagentStart"):
        n = next_state(s, ev(name), NOW)
        assert (n.model, n.context_tokens) == ("fable-5.1", 160203), name


# --- up_next: the "UP NEXT:" line from the last reply ---


def test_up_next_defaults_empty_and_survives_old_files():
    old = {"session_id": "s1", "state": "idle", "agents_running": 0}
    assert SessionState.from_dict(old).up_next == ""
    assert SessionState.from_dict({"session_id": "s1", "bogus": 1}).up_next == ""


def test_up_next_roundtrips_through_dict():
    s = SessionState(session_id="s1", up_next="run the tests")
    d = s.to_dict()
    assert d["up_next"] == "run the tests"
    assert SessionState.from_dict(d) == s


def test_user_prompt_submit_clears_up_next():
    s = SessionState(session_id="s1", state="done", up_next="run the tests")
    n = next_state(s, ev("UserPromptSubmit", prompt="go"), NOW)
    assert n.up_next == ""
    assert n.state == "working"


def test_injected_prompt_also_clears_up_next():
    s = SessionState(session_id="s1", state="done", up_next="run the tests")
    n = next_state(s, ev("UserPromptSubmit", prompt="<task-notification>x</task-notification>"), NOW)
    assert n.up_next == ""


@pytest.mark.parametrize("name", ["PostToolUse", "Stop", "SubagentStart", "PreToolUse", "Notification"])
def test_other_events_keep_up_next(name):
    s = SessionState(session_id="s1", state="working", up_next="run the tests")
    assert next_state(s, ev(name), NOW).up_next == "run the tests"
