"""Reading model and context size from the tail of a session transcript."""

import json

import pytest

from supclaude.transcript import fmt_tokens, read_last_up_next, read_last_usage, short_model


def assistant(model: str, *, sidechain: bool = False, usage: dict | None = None) -> str:
    msg: dict = {"role": "assistant", "model": model}
    if usage is not None:
        msg["usage"] = usage
    return json.dumps({"type": "assistant", "isSidechain": sidechain, "message": msg})


USAGE = {
    "input_tokens": 2,
    "cache_creation_input_tokens": 297,
    "cache_read_input_tokens": 160203,
    "output_tokens": 1232,
}


def write_fixture(path):
    """user, assistant(usage), sidechain assistant, >64 KiB tool_result, bad JSON."""
    huge = json.dumps({"type": "user", "message": {"role": "user", "content": "x" * 100_000}})
    lines = [
        json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}),
        assistant("claude-fable-5-1", usage=USAGE),
        assistant("claude-haiku-4-5-20251001", sidechain=True,
                  usage={"input_tokens": 1, "cache_read_input_tokens": 5}),
        huge,
        "{this is not json",
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


def test_reads_last_top_level_assistant_usage_across_chunk_growth(tmp_path):
    p = write_fixture(tmp_path / "t.jsonl")
    assert p.stat().st_size > 64 * 1024
    assert read_last_usage(str(p)) == ("claude-fable-5-1", 2 + 297 + 160203)


def test_missing_usage_keys_count_as_zero(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(assistant("claude-opus-5", usage={"input_tokens": 7}) + "\n")
    assert read_last_usage(str(p)) == ("claude-opus-5", 7)


def test_skips_assistant_lines_without_usage(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(
        assistant("claude-opus-5", usage={"input_tokens": 9}) + "\n"
        + assistant("claude-sonnet-5") + "\n"
    )
    assert read_last_usage(str(p)) == ("claude-opus-5", 9)


def test_last_line_wins(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(
        assistant("claude-opus-5", usage={"input_tokens": 1}) + "\n"
        + assistant("claude-sonnet-5", usage={"input_tokens": 2}) + "\n"
    )
    assert read_last_usage(str(p)) == ("claude-sonnet-5", 2)


def test_no_qualifying_line_returns_none(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps({"type": "user"}) + "\n")
    assert read_last_usage(str(p)) is None
    (tmp_path / "empty.jsonl").write_text("")
    assert read_last_usage(str(tmp_path / "empty.jsonl")) is None


def test_missing_file_returns_none(tmp_path):
    assert read_last_usage(str(tmp_path / "nope.jsonl")) is None


def test_small_file_without_trailing_newline(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(assistant("claude-opus-5", usage={"input_tokens": 3}))
    assert read_last_usage(str(p)) == ("claude-opus-5", 3)


@pytest.mark.parametrize(
    "raw, short",
    [
        ("claude-fable-5-1", "fable-5.1"),
        ("claude-opus-5", "opus-5"),
        ("claude-sonnet-5", "sonnet-5"),
        ("claude-haiku-4-5-20251001", "haiku-4.5"),
        ("claude-opus-5[1m]", "opus-5"),
        ("gpt-9", "gpt-9"),
        ("", ""),
    ],
)
def test_short_model(raw, short):
    assert short_model(raw) == short


@pytest.mark.parametrize(
    "n, s",
    [
        (0, "0"),
        (-5, "0"),
        (512, "512"),
        (999, "999"),
        (1000, "1.0k"),
        (9849, "9.8k"),
        (9950, "10k"),
        (160203, "160k"),
    ],
)
def test_fmt_tokens(n, s):
    assert fmt_tokens(n) == s


# --- UP NEXT line read from the last assistant text block ---


def text_line(text: str, *, sidechain: bool = False) -> str:
    msg = {"role": "assistant", "content": [{"type": "text", "text": text}]}
    return json.dumps({"type": "assistant", "isSidechain": sidechain, "message": msg})


def tool_use_line() -> str:
    msg = {"role": "assistant", "content": [{"type": "tool_use", "name": "Read", "input": {}}]}
    return json.dumps({"type": "assistant", "isSidechain": False, "message": msg})


def test_up_next_found_in_last_text_line(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(
        text_line("Done.\nUP NEXT: old thing") + "\n"
        + text_line("All green.\n\nUP NEXT: run the p4 planning tests") + "\n"
    )
    assert read_last_up_next(str(p)) == "run the p4 planning tests"


def test_up_next_skips_sidechain_lines(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(
        text_line("UP NEXT: main thing") + "\n"
        + text_line("UP NEXT: subagent thing", sidechain=True) + "\n"
    )
    assert read_last_up_next(str(p)) == "main thing"


def test_up_next_skips_tool_use_only_assistant_line_after_text(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(text_line("UP NEXT: main thing") + "\n" + tool_use_line() + "\n")
    assert read_last_up_next(str(p)) == "main thing"


def test_up_next_uses_last_marker_line_within_text(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(text_line("UP NEXT: first\nmore words\n  UP NEXT: second") + "\n")
    assert read_last_up_next(str(p)) == "second"


def test_up_next_newest_reply_without_marker_hides_older_marker(tmp_path):
    """A reply that forgot the marker must not surface a stale line from an older turn."""
    p = tmp_path / "t.jsonl"
    p.write_text(
        text_line("UP NEXT: old thing") + "\n"
        + json.dumps({"type": "user", "message": {"role": "user", "content": "ok"}}) + "\n"
        + text_line("Forgot the marker this time.") + "\n"
        + tool_use_line() + "\n"
    )
    assert read_last_up_next(str(p)) is None


def test_up_next_no_marker_returns_none(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(text_line("All done, nothing else.") + "\n" + json.dumps({"type": "user"}) + "\n")
    assert read_last_up_next(str(p)) is None


def test_up_next_missing_file_returns_none(tmp_path):
    assert read_last_up_next(str(tmp_path / "nope.jsonl")) is None


def test_up_next_malformed_json_returns_none(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text('{"type": "assistant", UP NEXT: broken\n')
    assert read_last_up_next(str(p)) is None


def test_up_next_strips_markdown_bold(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(text_line("**UP NEXT: ship it**") + "\n")
    assert read_last_up_next(str(p)) == "ship it"
    p.write_text(text_line("**UP NEXT:** ship it") + "\n")
    assert read_last_up_next(str(p)) == "ship it"


def test_up_next_collapses_whitespace_and_truncates(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(text_line("UP NEXT:   " + "word  " * 40) + "\n")
    got = read_last_up_next(str(p))
    assert got == " ".join(["word"] * 40)[:80]
    assert len(got) == 80


def test_up_next_found_across_chunk_growth(tmp_path):
    p = tmp_path / "t.jsonl"
    huge = json.dumps({"type": "user", "message": {"role": "user", "content": "x" * 100_000}})
    p.write_text(text_line("UP NEXT: far back") + "\n" + huge + "\n")
    assert p.stat().st_size > 64 * 1024
    assert read_last_up_next(str(p)) == "far back"


def test_up_next_from_text_is_public(tmp_path):
    from supclaude.transcript import up_next_from_text

    assert up_next_from_text("Done.\n\nUP NEXT: run the tests") == "run the tests"
    assert up_next_from_text("**UP NEXT: ship it**") == "ship it"
    assert up_next_from_text("no marker here") is None
    assert up_next_from_text("UP NEXT:   lots   of   space") == "lots of space"
    assert up_next_from_text("UP NEXT: " + "x" * 200) == "x" * 80
