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
