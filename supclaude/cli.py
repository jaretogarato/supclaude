"""`supclaude` command line entry point."""

from __future__ import annotations

import argparse
import sys

from supclaude import install as installer
from supclaude import store

REMINDER = (
    "Reminder: turn on the iTerm2 Python API:\n"
    "  iTerm2 -> Settings -> General -> Magic -> Enable Python API"
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="supclaude", description="Claude Code session dashboard for iTerm2")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("hook", help="(used by Claude Code) read a hook event from stdin")
    sub.add_parser("install", help="add hooks to ~/.claude/settings.json")
    sub.add_parser("uninstall", help="remove hooks from ~/.claude/settings.json")
    args = parser.parse_args(argv)

    if args.cmd == "hook":
        from supclaude.hook import main as hook_main
        hook_main()
        return

    if args.cmd == "install":
        cmd = installer.hook_command()
        installer.install(installer.default_settings_path(), cmd)
        store.state_dir()  # make sure ~/.supclaude/state/ exists
        print(f"Installed hooks -> {installer.default_settings_path()}")
        print(f"Hook command: {cmd}")
        print(REMINDER)
        return

    if args.cmd == "uninstall":
        installer.uninstall(installer.default_settings_path(), installer.hook_command())
        print("Removed SupClaude hooks.")
        return

    from supclaude.app import run_dashboard
    run_dashboard()


if __name__ == "__main__":
    main(sys.argv[1:])
