import json

from supclaude import install

CMD = "/opt/bin/supclaude hook"


def read(p):
    return json.loads(p.read_text())


def test_install_creates_file_and_all_events(tmp_path):
    p = tmp_path / "settings.json"
    install.install(p, CMD)
    d = read(p)
    for ev in install.HOOK_EVENTS:
        entries = d["hooks"][ev]
        assert entries == [{"hooks": [{"type": "command", "command": CMD}]}]


def test_install_keeps_existing_keys_and_hooks(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "statusLine": {"type": "command", "command": "foo"},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]},
    }))
    install.install(p, CMD)
    d = read(p)
    assert d["statusLine"]["command"] == "foo"
    stop = d["hooks"]["Stop"]
    assert stop[0]["hooks"][0]["command"] == "other"
    assert stop[1]["hooks"][0]["command"] == CMD


def test_install_twice_is_idempotent(tmp_path):
    p = tmp_path / "settings.json"
    install.install(p, CMD)
    install.install(p, CMD)
    d = read(p)
    assert len(d["hooks"]["Stop"]) == 1


def test_uninstall_removes_only_ours(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]},
    }))
    install.install(p, CMD)
    install.uninstall(p, CMD)
    d = read(p)
    assert d["hooks"]["Stop"] == [{"hooks": [{"type": "command", "command": "other"}]}]
    assert "SessionStart" not in d["hooks"]


def test_uninstall_on_missing_file_is_ok(tmp_path):
    install.uninstall(tmp_path / "nope.json", CMD)


def test_hook_command_is_absolute_and_ends_with_hook():
    cmd = install.hook_command()
    assert cmd.endswith(" hook")
    assert cmd.startswith("/")


def test_install_backs_up_original_once_and_leaves_no_temp_files(tmp_path):
    p = tmp_path / "settings.json"
    original = json.dumps({"statusLine": {"type": "command", "command": "foo"}})
    p.write_text(original)
    install.install(p, CMD)
    bak = tmp_path / "settings.json.bak-supclaude"
    assert bak.read_text() == original
    install.install(p, "/another/bin/supclaude hook")
    assert bak.read_text() == original
    assert [f.name for f in tmp_path.iterdir() if f.name.startswith(".tmp")] == []


def test_install_on_missing_file_makes_no_backup(tmp_path):
    p = tmp_path / "settings.json"
    install.install(p, CMD)
    assert not (tmp_path / "settings.json.bak-supclaude").exists()


def test_install_replaces_our_entry_from_a_different_path(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"hooks": {"Stop": [
        {"hooks": [{"type": "command", "command": "/old/path/supclaude hook"}]},
        {"hooks": [{"type": "command", "command": "other"}]},
    ]}}))
    install.install(p, "/new/path/supclaude hook")
    stop = read(p)["hooks"]["Stop"]
    ours = [e for e in stop if e["hooks"][0]["command"].endswith("supclaude hook")]
    assert len(ours) == 1
    assert ours[0]["hooks"][0]["command"] == "/new/path/supclaude hook"
    assert any(e["hooks"][0]["command"] == "other" for e in stop)


def test_uninstall_removes_our_entry_installed_from_any_path(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"hooks": {"Stop": [
        {"hooks": [{"type": "command", "command": "/somewhere/.venv/bin/supclaude hook"}]},
    ]}}))
    install.uninstall(p, CMD)
    assert "hooks" not in read(p)


def test_uninstall_with_nothing_of_ours_does_not_rewrite(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]}}))
    before = p.read_text()
    install.uninstall(p, CMD)
    assert p.read_text() == before
