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


# --- per-session advisory lock ---


def test_locked_blocks_second_holder():
    import threading

    acquired = threading.Event()

    def contender():
        with store.locked("s1"):
            acquired.set()

    with store.locked("s1"):
        t = threading.Thread(target=contender)
        t.start()
        assert not acquired.wait(0.2), "second holder got the lock while it was held"
    assert acquired.wait(2.0)
    t.join()


def test_locked_different_sessions_do_not_block():
    import threading

    acquired = threading.Event()

    def contender():
        with store.locked("other"):
            acquired.set()

    with store.locked("s1"):
        t = threading.Thread(target=contender)
        t.start()
        assert acquired.wait(2.0)
    t.join()


def test_lock_files_are_not_sessions():
    store.save(SessionState(session_id="s1", pid=os.getpid()))
    with store.locked("s1"):
        pass
    with store.locked("ghost"):
        pass
    assert (store.state_dir() / "s1.lock").exists()
    assert [s.session_id for s in store.load_all()] == ["s1"]
    assert [s.session_id for s in store.prune_dead()] == ["s1"]


def test_delete_removes_lock_file_too():
    store.save(SessionState(session_id="s1"))
    with store.locked("s1"):
        pass
    assert (store.state_dir() / "s1.lock").exists()
    store.delete("s1")
    assert not store.path_for("s1").exists()
    assert not (store.state_dir() / "s1.lock").exists()
    store.delete("s1")  # no lock file, no state file: still fine


def test_mark_seen_takes_the_session_lock(monkeypatch):
    held = []
    real_locked = store.locked

    def spy(session_id):
        held.append(session_id)
        return real_locked(session_id)

    monkeypatch.setattr(store, "locked", spy)
    store.save(SessionState(session_id="d", state="done"))
    store.mark_seen("d")
    assert held == ["d"]
    assert store.load("d").state == "idle"
