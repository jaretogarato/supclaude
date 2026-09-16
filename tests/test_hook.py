import json

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


def test_session_start_refreshes_iterm_id_and_pid():
    """`claude --resume` reuses the session id in a new tab/process: refresh both."""
    hook.run(payload("SessionStart"), {"ITERM_SESSION_ID": "w0t1p0:A"}, now=NOW, pid=1)
    hook.run(payload("SessionStart"), {"ITERM_SESSION_ID": "w0t2p0:B"}, now=NOW, pid=2)
    s = store.load("s1")
    assert s.iterm_session_id == "w0t2p0:B"
    assert s.pid == 2


def test_non_session_start_events_keep_existing_iterm_id_and_pid():
    hook.run(payload("SessionStart"), {"ITERM_SESSION_ID": "w0t2p0:B"}, now=NOW, pid=2)
    hook.run(payload("Stop"), {"ITERM_SESSION_ID": "w0t3p0:C"}, now=NOW, pid=3)
    s = store.load("s1")
    assert s.iterm_session_id == "w0t2p0:B"
    assert s.pid == 2


def test_find_claude_pid_matches_executable_basename_not_substring(monkeypatch):
    chain = {
        100: "200 /bin/zsh -c source /x/.claude/shell-snapshots/snap.sh",
        200: "300 /usr/local/bin/claude",
    }

    class FakeResult:
        def __init__(self, stdout):
            self.stdout = stdout

    def fake_run(argv, **kwargs):
        return FakeResult(chain.get(int(argv[-1]), ""))

    monkeypatch.setattr(hook.os, "getppid", lambda: 100)
    monkeypatch.setattr(hook.subprocess, "run", fake_run)
    assert hook.find_claude_pid() == 200


def test_find_claude_pid_matches_directory_component_named_claude(monkeypatch):
    chain = {
        100: "200 /bin/zsh -c source /x/.claude/shell-snapshots/snap.sh",
        200: "300 /Users/x/.local/share/claude/versions/2.1.223 --append-system-prompt foo",
    }

    class FakeResult:
        def __init__(self, stdout):
            self.stdout = stdout

    def fake_run(argv, **kwargs):
        return FakeResult(chain.get(int(argv[-1]), ""))

    monkeypatch.setattr(hook.os, "getppid", lambda: 100)
    monkeypatch.setattr(hook.subprocess, "run", fake_run)
    assert hook.find_claude_pid() == 200


def test_find_claude_pid_rejects_dotclaude_supclaude_and_claude_app(monkeypatch):
    chain = {
        100: "200 /x/.claude/shell-snapshots/snap.sh",
        200: "300 /opt/supclaude/bin/supclaude hook",
        300: "1 /Applications/Claude.app/Contents/MacOS/Claude",
    }

    class FakeResult:
        def __init__(self, stdout):
            self.stdout = stdout

    def fake_run(argv, **kwargs):
        return FakeResult(chain.get(int(argv[-1]), ""))

    monkeypatch.setattr(hook.os, "getppid", lambda: 100)
    monkeypatch.setattr(hook.subprocess, "run", fake_run)
    assert hook.find_claude_pid() == 100


# --- concurrent hook processes must not lose updates ---


def test_hook_run_leaves_no_lock_counted_as_session():
    hook.run(payload("SessionStart"), ENV, now=NOW, pid=1)
    hook.run(payload("SubagentStart", agent_id="a1"), ENV, now=NOW, pid=1)
    assert (store.state_dir() / "s1.lock").exists()
    assert [s.session_id for s in store.load_all()] == ["s1"]


def test_hook_run_takes_the_session_lock(monkeypatch):
    held = []
    real_locked = store.locked

    def spy(session_id):
        held.append(session_id)
        return real_locked(session_id)

    monkeypatch.setattr(store, "locked", spy)
    hook.run(payload("SessionStart"), ENV, now=NOW, pid=1)
    assert held == ["s1"]


def test_concurrent_subagent_start_and_post_tool_use_keep_count():
    """SubagentStart and PostToolUse(Agent) fire as two processes at the same
    instant. Without a lock, PostToolUse can save a stale agents_running=0 over
    SubagentStart's 1."""
    import threading

    start = payload("SubagentStart", agent_id="a1")
    post = payload("PostToolUse", tool_name="Agent")
    for i in range(200):
        store.save(store.SessionState(session_id="s1", state="working", pid=1))
        go = threading.Barrier(2)

        def fire(text):
            go.wait()
            hook.run(text, ENV, now=NOW, pid=1)

        threads = [threading.Thread(target=fire, args=(start,)),
                   threading.Thread(target=fire, args=(post,))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        s = store.load("s1")
        assert s.agents_running == 1, f"lost update on iteration {i}"
        assert s.agent_ids == ["a1"]
        assert s.state == "working"


# --- model and context size read from the transcript ---


def transcript(tmp_path, model="claude-fable-5-1", ctx=(2, 297, 160203)):
    p = tmp_path / "transcript.jsonl"
    line = {
        "type": "assistant",
        "isSidechain": False,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": ctx[0],
                "cache_creation_input_tokens": ctx[1],
                "cache_read_input_tokens": ctx[2],
                "output_tokens": 5,
            },
        },
    }
    p.write_text(json.dumps({"type": "user"}) + "\n" + json.dumps(line) + "\n")
    return str(p)


def test_stop_reads_model_and_context_from_transcript(tmp_path):
    hook.run(payload("SessionStart"), ENV, now=NOW, pid=1)
    hook.run(payload("Stop", transcript_path=transcript(tmp_path)), ENV, now=NOW, pid=1)
    s = store.load("s1")
    assert s.model == "fable-5.1"
    assert s.context_tokens == 160502
    assert s.state == "done"


def test_subagent_tool_events_do_not_touch_model_or_context(tmp_path):
    hook.run(payload("SessionStart"), ENV, now=NOW, pid=1)
    hook.run(payload("Stop", transcript_path=transcript(tmp_path)), ENV, now=NOW, pid=1)
    (tmp_path / "sub").mkdir()
    sub = transcript(tmp_path / "sub", model="claude-haiku-4-5-20251001", ctx=(1, 1, 1))
    hook.run(
        payload("PostToolUse", tool_name="Read", agent_id="a1", transcript_path=sub),
        ENV, now=NOW, pid=1,
    )
    s = store.load("s1")
    assert s.model == "fable-5.1"
    assert s.context_tokens == 160502


def test_missing_transcript_leaves_fields_unchanged_and_does_not_raise(tmp_path):
    hook.run(payload("SessionStart"), ENV, now=NOW, pid=1)
    hook.run(payload("Stop", transcript_path=transcript(tmp_path)), ENV, now=NOW, pid=1)
    hook.run(
        payload("UserPromptSubmit", prompt="go", transcript_path=str(tmp_path / "gone.jsonl")),
        ENV, now=NOW, pid=1,
    )
    s = store.load("s1")
    assert s.state == "working"
    assert s.model == "fable-5.1"
    assert s.context_tokens == 160502


def test_events_outside_the_read_set_do_not_read_transcript(tmp_path):
    hook.run(payload("SessionStart", transcript_path=transcript(tmp_path)), ENV, now=NOW, pid=1)
    s = store.load("s1")
    assert s.model == ""
    assert s.context_tokens == 0


# --- up_next read from the transcript on Stop ---


def transcript_with_text(tmp_path, text, name="transcript.jsonl"):
    p = tmp_path / name
    line = {
        "type": "assistant",
        "isSidechain": False,
        "message": {
            "model": "claude-fable-5-1",
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 1, "cache_read_input_tokens": 2},
        },
    }
    p.write_text(json.dumps({"type": "user"}) + "\n" + json.dumps(line) + "\n")
    return str(p)


def test_stop_fills_up_next_from_transcript(tmp_path):
    hook.run(payload("SessionStart"), ENV, now=NOW, pid=1)
    path = transcript_with_text(tmp_path, "Done.\n\nUP NEXT: run the p4 planning tests")
    hook.run(payload("Stop", transcript_path=path), ENV, now=NOW, pid=1)
    s = store.load("s1")
    assert s.up_next == "run the p4 planning tests"
    assert s.model == "fable-5.1"  # usage read still happens alongside


def test_post_tool_use_does_not_read_up_next(tmp_path):
    hook.run(payload("SessionStart"), ENV, now=NOW, pid=1)
    path = transcript_with_text(tmp_path, "UP NEXT: not yet")
    hook.run(payload("PostToolUse", tool_name="Read", transcript_path=path), ENV, now=NOW, pid=1)
    assert store.load("s1").up_next == ""


def test_stop_without_marker_leaves_up_next_unchanged(tmp_path):
    hook.run(payload("SessionStart"), ENV, now=NOW, pid=1)
    first = transcript_with_text(tmp_path, "UP NEXT: keep me", name="a.jsonl")
    hook.run(payload("Stop", transcript_path=first), ENV, now=NOW, pid=1)
    second = transcript_with_text(tmp_path, "no marker here", name="b.jsonl")
    hook.run(payload("Stop", transcript_path=second), ENV, now=NOW, pid=1)
    assert store.load("s1").up_next == "keep me"


def test_subagent_stop_with_agent_id_does_not_read_up_next(tmp_path):
    hook.run(payload("SessionStart"), ENV, now=NOW, pid=1)
    path = transcript_with_text(tmp_path, "UP NEXT: subagent line")
    hook.run(payload("Stop", agent_id="a1", transcript_path=path), ENV, now=NOW, pid=1)
    assert store.load("s1").up_next == ""


def test_user_prompt_submit_clears_up_next_via_hook(tmp_path):
    hook.run(payload("SessionStart"), ENV, now=NOW, pid=1)
    path = transcript_with_text(tmp_path, "UP NEXT: stale after next prompt")
    hook.run(payload("Stop", transcript_path=path), ENV, now=NOW, pid=1)
    assert store.load("s1").up_next == "stale after next prompt"
    hook.run(payload("UserPromptSubmit", prompt="go", transcript_path=path), ENV, now=NOW, pid=1)
    assert store.load("s1").up_next == ""


# --- /clear: the new session inherits the model of the tab's previous one ---


def test_session_end_stashes_the_model_under_the_pid(tmp_path):
    hook.run(payload("SessionStart"), ENV, now=NOW, pid=4242)
    hook.run(payload("Stop", transcript_path=transcript(tmp_path)), ENV, now=NOW, pid=4242)
    hook.run(payload("SessionEnd"), ENV, now=NOW, pid=4242)
    assert store.load("s1") is None
    assert store.carry_path_for(4242).exists()


def test_session_start_from_clear_restores_the_carried_model(tmp_path):
    hook.run(payload("SessionStart"), ENV, now=NOW, pid=4242)
    hook.run(payload("Stop", transcript_path=transcript(tmp_path)), ENV, now=NOW, pid=4242)
    hook.run(payload("SessionEnd"), ENV, now=NOW, pid=4242)
    hook.run(payload("SessionStart", session_id="s2", source="clear"), ENV, now=NOW, pid=4242)
    s = store.load("s2")
    assert s.model == "fable-5.1"
    assert s.context_tokens == 0
    assert not store.carry_path_for(4242).exists()


def test_session_start_from_startup_does_not_restore_the_model():
    store.carry_save(4242, "fable-5.1")
    hook.run(payload("SessionStart", session_id="s2", source="startup"), ENV, now=NOW, pid=4242)
    assert store.load("s2").model == ""


def test_session_start_model_field_wins_over_the_carried_model():
    store.carry_save(4242, "fable-5.1")
    hook.run(
        payload("SessionStart", session_id="s2", source="clear", model="claude-opus-5"),
        ENV, now=NOW, pid=4242,
    )
    assert store.load("s2").model == "opus-5"


def test_session_start_model_field_may_be_a_dict():
    hook.run(
        payload("SessionStart", session_id="s2", source="clear",
                model={"id": "claude-haiku-4-5-20251001"}),
        ENV, now=NOW, pid=4242,
    )
    assert store.load("s2").model == "haiku-4.5"
