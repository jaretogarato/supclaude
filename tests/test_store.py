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


# --- carry area: hand the model from a dying session to the next one on the pid ---


def test_carry_dir_is_created_under_home(home):
    d = store.carry_dir()
    assert d == home / "carry"
    assert d.is_dir()
    assert store.carry_path_for(7) == d / "7.json"


def test_carry_save_then_take_returns_the_model_and_removes_the_file():
    store.carry_save(4242, "fable-5.1")
    assert store.carry_path_for(4242).exists()
    assert store.carry_take(4242) == "fable-5.1"
    assert not store.carry_path_for(4242).exists()
    assert store.carry_take(4242) == ""


def test_carry_take_on_a_missing_pid_returns_empty():
    assert store.carry_take(2_000_000_000) == ""


def test_carry_ignores_non_positive_pids_and_empty_models():
    store.carry_save(0, "fable-5.1")
    store.carry_save(-1, "fable-5.1")
    store.carry_save(4242, "")
    assert list(store.carry_dir().iterdir()) == []
    assert store.carry_take(0) == ""
    assert store.carry_take(-1) == ""


def test_carry_take_on_malformed_content_returns_empty():
    store.carry_dir()
    store.carry_path_for(4242).write_text("{not json")
    assert store.carry_take(4242) == ""
    store.carry_path_for(4242).write_text(json.dumps({"model": 7}))
    assert store.carry_take(4242) == ""


def test_carry_take_falls_back_to_a_state_with_the_same_pid():
    """SessionEnd and SessionStart hold different locks and can run in either order."""
    store.save(SessionState(session_id="pre-clear", pid=4242, model="fable-5.1"))
    assert store.carry_take(4242) == "fable-5.1"


def test_carry_take_fallback_ignores_other_pids_and_blank_models():
    store.save(SessionState(session_id="other-tab", pid=99, model="fable-5.1"))
    store.save(SessionState(session_id="no-model", pid=4242, model=""))
    assert store.carry_take(4242) == ""


def test_prune_dead_removes_carry_files_for_dead_pids_only():
    store.carry_save(os.getpid(), "fable-5.1")
    store.carry_save(2_000_000_000, "haiku-4.5")
    stray = store.carry_dir() / "notapid.json"
    stray.write_text("{}")
    store.prune_dead()
    assert store.carry_path_for(os.getpid()).exists()
    assert not store.carry_path_for(2_000_000_000).exists()
    assert stray.exists()


def test_carry_take_prefers_a_live_state_over_a_stale_carry_file():
    """An unconsumed carry file from an earlier /clear must not beat current state.

    When SessionStart:clear wins the race against SessionEnd, the stash is never
    taken and keeps a model that may since have changed. A state file with the
    same pid is the tab's actual pre-clear session, so it wins.
    """
    store.carry_save(4242, "stale-model")
    store.save(SessionState(session_id="live", pid=4242, model="fable-5.1"))
    assert store.carry_take(4242) == "fable-5.1"
    assert not store.carry_path_for(4242).exists()
