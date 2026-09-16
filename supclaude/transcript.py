"""Read the current model, context size and "UP NEXT" line from a session transcript's tail.

Claude Code writes each session to a JSONL file (`transcript_path` in every hook
event). Hook events carry neither the model nor token counts nor the reply text,
but every assistant reply in the transcript does. Only the tail of the file is
read, so the cost stays flat as transcripts grow to many megabytes.
"""

from __future__ import annotations

import json
import os

CHUNK_START = 64 * 1024
CHUNK_MAX = 4 * 1024 * 1024
CHUNK_GROWTH = 4

CONTEXT_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")

# Every reply ends with a plain-text line "UP NEXT: <what the user should do next>".
UP_NEXT_PREFIX = "UP NEXT:"
UP_NEXT_MAX = 80


def _int(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def _usage_from_line(raw: bytes) -> tuple[str, int] | None:
    """(model, context_tokens) for a top-level assistant line with usage, else None."""
    raw = raw.strip()
    # Cheap pre-filter: most lines (tool results, user turns) never need parsing.
    if not raw or b'"usage"' not in raw:
        return None
    try:
        obj = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(obj, dict) or obj.get("type") != "assistant" or obj.get("isSidechain"):
        return None
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return None
    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return None
    model = str(msg.get("model") or "")
    return model, sum(_int(usage.get(k)) for k in CONTEXT_KEYS)


def _tail_lines(path: str):
    """Yield raw lines from the end of the file, newest first.

    Reads a growing tail window (64 KiB, x4 up to 4 MiB) so the whole file is
    never loaded. When the window grows, lines already yielded from the smaller
    window are yielded again; callers stop at the first match so that is harmless.
    Raises OSError like open() does; callers turn that into None.
    """
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        chunk = CHUNK_START
        while True:
            start = max(0, size - chunk)
            f.seek(start)
            lines = f.read(size - start).split(b"\n")
            if start > 0:
                lines = lines[1:]  # first line of a mid-file window is a fragment
            yield from reversed(lines)
            if start == 0 or chunk >= CHUNK_MAX:
                return
            chunk *= CHUNK_GROWTH


def read_last_usage(path: str) -> tuple[str, int] | None:
    """(model, context_tokens) from the last qualifying assistant line, or None.

    Context size is input + cache_creation_input + cache_read_input of that
    line, which is what the model saw on its most recent turn. Sidechain
    (subagent) lines and lines without usage are skipped. Any OSError or
    malformed content yields None rather than an exception.
    """
    try:
        for raw in _tail_lines(path):
            found = _usage_from_line(raw)
            if found is not None:
                return found
        return None
    except OSError:
        return None


def _strip_bold(s: str) -> str:
    s = s.strip()
    if s.startswith("**"):
        s = s[2:]
    if s.endswith("**"):
        s = s[:-2]
    return s.strip()


def up_next_from_text(text: str) -> str | None:
    """The last "UP NEXT: ..." line of a reply, prefix and bold markers stripped."""
    for line in reversed(text.splitlines()):
        line = _strip_bold(line)
        if not line.startswith(UP_NEXT_PREFIX):
            continue
        rest = " ".join(_strip_bold(line[len(UP_NEXT_PREFIX):]).split())
        return rest[:UP_NEXT_MAX] or None
    return None


def _reply_text_from_line(raw: bytes) -> str | None:
    """Joined text blocks of a top-level assistant line, or None if it is not one.

    None means "keep looking": a user/tool line, a sidechain line, a tool_use-only
    assistant line, or malformed JSON. A str (possibly without any marker) means
    this line is the newest reply and decides the result.
    """
    raw = raw.strip()
    if not raw or b'"assistant"' not in raw:
        return None
    try:
        obj = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(obj, dict) or obj.get("type") != "assistant" or obj.get("isSidechain"):
        return None
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return None
    content = msg.get("content")
    if not isinstance(content, list):
        return None
    texts = [b.get("text") for b in content
             if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)]
    if not texts:
        return None  # tool_use-only line
    return "\n".join(texts)


def read_last_up_next(path: str) -> str | None:
    """The "UP NEXT:" line from the newest top-level assistant reply, or None.

    Walks the transcript tail newest-first. The first line that is a top-level
    (non-sidechain) assistant line with a text block decides the result: its
    "UP NEXT:" text if present, else None. It never reaches back to an older
    reply, so a reply that forgot the marker yields None rather than a stale
    next step. Any OSError or malformed content yields None rather than an
    exception.
    """
    try:
        for raw in _tail_lines(path):
            text = _reply_text_from_line(raw)
            if text is not None:
                return up_next_from_text(text)
        return None
    except OSError:
        return None


def short_model(name: str) -> str:
    """"claude-fable-5-1" -> "fable-5.1", "claude-haiku-4-5-20251001" -> "haiku-4.5".

    Strips a trailing "[...]" (context-window tag), the "claude-" prefix and a
    trailing 8-digit date, then joins a final "-<n>-<m>" as "-<n>.<m>". Names
    that do not fit that shape pass through unchanged.
    """
    name = (name or "").strip()
    if name.endswith("]"):
        i = name.rfind("[")
        if i >= 0:
            name = name[:i]
    if name.startswith("claude-"):
        name = name[len("claude-"):]
    parts = name.split("-")
    if len(parts) > 1 and len(parts[-1]) == 8 and parts[-1].isdigit():
        parts.pop()
    if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
        parts[-2:] = [f"{parts[-2]}.{parts[-1]}"]
    return "-".join(parts)


def fmt_tokens(n: int) -> str:
    """0 -> "0", 512 -> "512", 9849 -> "9.8k", 160203 -> "160k".

    A freshly cleared session shows a green "0" rather than a blank cell, which
    reads as "the context just reset".
    """
    if n <= 0:
        return "0"
    if n < 1000:
        return str(n)
    if n < 10000:
        tenths = (n + 50) // 100  # integer math: no float rounding surprises at .x5
        if tenths >= 100:
            return "10k"
        return f"{tenths // 10}.{tenths % 10}k"
    return f"{(n + 500) // 1000}k"
