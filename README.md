# SupClaude

A tiny iTerm2 window that shows the state of every Claude Code session running in your other iTerm2 tabs. It colors those tabs to match, and it can jump you to any session with one key.

If you run many Claude Code sessions at once and keep losing track of which one needs you, this is for you.

Directed by me; mostly written by Claude Code. 

## What you need

- macOS with [iTerm2](https://iterm2.com) 3.3 or newer (the Python API arrived in 3.3). SupClaude only works inside iTerm2. The hook finds each tab through iTerm2's `ITERM_SESSION_ID` environment variable, and jumping and tab colors use the iTerm2 Python API.
- [Claude Code](https://claude.com/claude-code).
- Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

## States

| Word | Color | Meaning |
|---|---|---|
| WORKING | blue | Claude is on a task |
| NEEDS YOU | hot pink | Claude asked a question or needs a permission |
| DONE | green | Claude finished and you have not looked yet |
| AGENTS | yellow | Claude is resting, background agents still run |
| IDLE | gray | Resting, nothing new |

A DONE row turns IDLE on its own as soon as you focus that session's pane. Colors live in `supclaude/colors.py`. Change them there.

## Install

```bash
git clone https://github.com/jaretogarato/supclaude.git
cd supclaude
uv tool install --editable .
supclaude install
```

`supclaude install` adds hooks to `~/.claude/settings.json`. It keeps a backup at `~/.claude/settings.json.bak-supclaude` and leaves your other hooks alone.

Then turn on the iTerm2 API: iTerm2 → Settings → General → Magic → Enable Python API.

## Run

Open a small iTerm2 window and run:

```bash
supclaude
```

Keys: `1`–`9`, `Enter`, or double-click jump to that session's tab. `r` refresh. `q` quit.

Columns: `model` and `ctx` show the top-level model and how many tokens are in that session's context window right now, read from the session transcript on each turn. After a `/clear`, `model` carries over from that tab's previous session and `ctx` shows a green `0` until the first reply lands.

`up next` is the last column. It shows the last line of the reply that starts with `UP NEXT:`, which Claude writes when your `~/.claude/CLAUDE.md` asks it to. It lights up in the row's color when Claude is waiting on you.

### Turning on the up next column

Add this to `~/.claude/CLAUDE.md` and Claude ends every reply with a line SupClaude can read:

```
At the end of every reply, add one final line that starts with "UP NEXT:".
Rules:
- It is the last line. Plain text on its own line. No bold, no code block.
- Keep it under 60 characters.
- Say the next concrete action, e.g. "UP NEXT: run the p4 planning tests".
- If you need something from me, say so: "UP NEXT: waiting for you to pick 1 or 2".
- If nothing is left, write "UP NEXT: done".
- Do this on every reply, even short ones and questions.
Why: a terminal app reads this line and shows me what each local agent is doing next.
```

Any Claude Code session you start after `supclaude install` shows up. Sessions that were already running show up on their next hook event, such as your next prompt.

## How it finds the right tab

Every Claude Code session runs in one iTerm2 pane. When Claude starts, the hook records that pane's iTerm2 session id. The dashboard uses that id for everything:

- **Jumping** activates that exact pane. iTerm2 selects its tab and brings its window to the front, so it works even when your sessions are spread over several windows.
- **Tab colors** are set through that pane's profile, so the color follows the Claude pane.
- **Seen detection** watches which pane has focus. When you land on a DONE session, it turns IDLE.

The `session` column shows the name you gave that iTerm2 tab, so the dashboard rows and your tab bar line up. When iTerm2's Python API is off, or the tab has no custom name, it falls back to the name of the working directory's folder. Two Claude sessions running in two panes of the same tab share that tab's name, so both rows show the same thing.

## How I work, and why SupClaude looks like this

I keep one iTerm2 window with a tab per project. Each tab is split into panes: one for Claude Code, one for terminal and git commands, one or more for the project's dev servers, and sometimes an ssh pane to a remote box. I name each tab after the project folder. Then I run `supclaude` in a second, small window off to the side.

With that setup the dashboard is a single glance: which project is working, which one is waiting on me, which one finished. The tab colors say the same thing in the main window, and the number keys drop me into the right pane.

SupClaude is built around this way of working. If you work differently and want to adapt it, fork the repo, make your change on a branch, and open a pull request. I am open to that.

## Launchers like happy

SupClaude finds a session's Claude process by walking up the parent process tree. It accepts a process whose executable is named `claude`, or whose path has a `claude` folder in it. That second rule covers launchers such as [happy](https://happy.engineering), a phone and web client for Claude Code, which starts `~/.local/share/claude/versions/<version>` directly instead of a `claude` binary.

If you start Claude through some other wrapper and its sessions drop off the dashboard after a moment, that check in `supclaude/hook.py` is the place to look.

## Built with Textual

The dashboard is a [Textual](https://textual.textualize.io) app. Textual is a Python framework for apps that run inside the terminal, which is why the dashboard lives in an iTerm2 window like everything else. All the screen code is in `supclaude/app.py`.

## How it works

Claude Code hooks call `supclaude hook` on each event. That writes `~/.supclaude/state/<session>.json`. The dashboard polls that folder twice a second and talks to iTerm2 over its Python API for focus, tab colors, and jumping.

To see what the iTerm2 bridge is doing, run `SUPCLAUDE_DEBUG=1 supclaude` and read `~/.supclaude/dashboard.log`.

To log every hook event, create the file `~/.supclaude/trace` (or set `SUPCLAUDE_TRACE=1`); events go to `~/.supclaude/hook.log`. Delete the file to stop.

## Uninstall

```bash
supclaude uninstall
uv tool uninstall supclaude
```

`supclaude uninstall` removes only the hooks it added.

## Develop

```bash
uv run pytest -q
```

## License

MIT licensed. See `LICENSE`.
