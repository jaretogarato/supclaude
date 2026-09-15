"""Reading model and context size from the tail of a session transcript."""

import json

import pytest

from supclaude.transcript import fmt_tokens, read_last_usage, short_model


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
        (0, ""),
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
