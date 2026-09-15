# SupClaude

A tiny iTerm2 window that shows the state of every Claude Code session in your other tabs. It colors those tabs too.

It only works inside iTerm2: the hook finds each tab through iTerm2's `ITERM_SESSION_ID` environment variable.

## States

| Word | Color | Meaning |
|---|---|---|
| WORKING | blue | Claude is on a task |
| NEEDS YOU | hot pink | Claude asked a question or needs a permission |
| DONE | green | Claude finished and you have not looked yet |
| AGENTS | yellow | Claude is resting, background agents still run |
| IDLE | gray | Resting, nothing new |

Colors live in `supclaude/colors.py`. Change them there.

## Install

```bash
uv tool install --editable .
supclaude install
```

Turn on the iTerm2 API: iTerm2 → Settings → General → Magic → Enable Python API.

## Run

```bash
supclaude
```

Keys: `1`–`9`, `Enter`, or double-click jump to that session's tab. `r` refresh. `q` quit.

## Uninstall

```bash
supclaude uninstall
uv tool uninstall supclaude
```

## How it works

Claude Code hooks call `supclaude hook` on each event. That writes `~/.supclaude/state/<session>.json`. The dashboard polls that folder and talks to iTerm2 over its Python API for focus, tab colors, and jumping.
