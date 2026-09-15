# SupClaude — Design

Date: 2026-09-14

## Goal

One small iTerm2 window shows the state of every Claude Code session that runs in other iTerm2 tabs. Each row shows a color and a short word for the state. iTerm2 tab colors match. A key press jumps to a session.

## States

| State | Word shown | Color name | Hex |
|---|---|---|---|
| Working | WORKING | blue | `#3B82F6` |
| Waiting for you | NEEDS YOU | hot pink | `#FF69B4` |
| Done, not seen | DONE | green | `#22C55E` |
| Resting, agents run | AGENTS | yellow | `#EAB308` |
| Resting / Done, seen | IDLE | gray | `#6B7280` |

Hex values live in one file: `supclaude/colors.py` (the Color Authority). Nothing else hard-codes a color. The dashboard and the iTerm tab colors both read from it.

## Parts

### 1. Sensor: `supclaude/hook.py`

Claude Code runs this script on hook events. It is registered in `~/.claude/settings.json` for these events:

`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PermissionRequest`, `Notification`, `SubagentStart`, `SubagentStop`, `Stop`, `SessionEnd`.

Input: hook JSON on stdin (`session_id`, `cwd`, `hook_event_name`, plus event fields). Environment: `ITERM_SESSION_ID` (inherited from the tab shell), parent pid.

Output: `~/.supclaude/state/<session_id>.json`:

```json
{
  "session_id": "...",
  "iterm_session_id": "w0t10p0:04548B7D-...",
  "cwd": "/Users/x/Projects/Foo",
  "name": "Foo",
  "state": "working",
  "agents_running": 0,
  "last_prompt": "first 80 chars of the last prompt",
  "updated_at": "2026-09-14T10:00:00Z",
  "pid": 12345
}
```

Writes are atomic: write to a temp file, then rename.

Rules (pure function `next_state(current, event) -> new`):

- `SessionStart` → `idle`, `agents_running = 0`
- `UserPromptSubmit` → `working`, store `last_prompt`
- `PreToolUse` with `tool_name == "AskUserQuestion"` → `needs_you`
- `PermissionRequest` → `needs_you`
- `Notification` with `notification_type` in {`permission_prompt`, `agent_needs_input`, `elicitation_dialog`} → `needs_you`
- `PostToolUse` while `needs_you` → `working`
- `SubagentStart` → `agents_running += 1`
- `SubagentStop` → `agents_running -= 1` (floor 0). If state is `agents` and count hits 0 → `done`
- `Stop` → if `agents_running > 0` then `agents` else `done`
- `SessionEnd` → delete the file

The hook script must never block Claude. It exits 0 always. Errors go to `~/.supclaude/hook.log`.

### 2. Dashboard: `supclaude/app.py`

Python, Textual for the UI, `iterm2` package for tabs.

Loop:

1. Watch `~/.supclaude/state/` (poll every 0.5 s; watchdog is optional later).
2. Drop rows whose `pid` is dead. Delete their file.
3. Ask iTerm2 for the focused session ID. Subscribe to focus-change events.
4. If a `done` session's tab gets focus after `updated_at` → mark `seen` (write `seen_at` into the file). `done` + `seen` shows as IDLE.
5. Render one row per session: index, name, state word, last prompt, age.
6. Set each tab's color from `colors.py`. Restore default color on quit and on `SessionEnd`.

Keys: `1`–`9` focus that session's tab. `r` refresh. `q` quit.

Sort: NEEDS YOU first, then DONE, then WORKING, then AGENTS, then IDLE.

### 3. Install: `supclaude install`

- Adds the hook entries to `~/.claude/settings.json` (merge, do not clobber).
- Creates `~/.supclaude/state/`.
- Prints a reminder: iTerm2 → Settings → General → Magic → Enable Python API.

`supclaude uninstall` removes the hook entries.

## Packaging

- `pyproject.toml`, installed with `uv tool install .`
- Entry point: `supclaude` → CLI with sub-commands `install`, `uninstall`, `hook`, and default = run the dashboard.
- The hook command in settings.json is `supclaude hook` so the path is stable.

## Error handling

- Hook: any exception → log and exit 0.
- Dashboard: iTerm2 API not enabled → show a banner with the setting to turn on. Still show rows from files.
- Bad or half-written state file → skip that row this tick.

## Tests

- `tests/test_state.py`: table-driven tests for `next_state` with fake hook JSON.
- `tests/test_store.py`: write, read, atomic rename, dead-pid cleanup.
- `tests/test_install.py`: settings.json merge keeps existing keys.
- iTerm2 parts are tested by hand.

## Out of scope (v1)

Sounds, macOS notifications, Herdr, tmux, non-iTerm terminals.
