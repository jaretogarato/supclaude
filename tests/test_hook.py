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
