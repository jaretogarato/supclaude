import re

import pytest

from supclaude import colors

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def test_every_state_has_color_label_and_sort():
    assert colors.STATES == ("working", "needs_you", "done", "agents", "idle")
    for s in colors.STATES:
        assert HEX.match(colors.COLORS[s]), s
        assert colors.LABELS[s]
        assert s in colors.SORT_ORDER


def test_waiting_is_hot_pink():
    assert colors.COLORS["needs_you"].upper() == "#FF69B4"


def test_sort_order_puts_needs_you_first_and_idle_last():
    order = sorted(colors.STATES, key=lambda s: colors.SORT_ORDER[s])
    assert order[0] == "needs_you"
    assert order[-1] == "idle"


def test_hex_to_rgb():
    assert colors.hex_to_rgb("#FF69B4") == (255, 105, 180)
    assert colors.hex_to_rgb("3b82f6") == (59, 130, 246)


CTX_BOUNDARIES = [
    (0, "#4CAF50"),
    (49_999, "#4CAF50"),
    (50_000, "#EECF6D"),
    (99_999, "#EECF6D"),
    (100_000, "#D5AC4E"),
    (149_999, "#D5AC4E"),
    (150_000, "#E87543"),
    (199_999, "#E87543"),
    (200_000, "#C9190C"),
    (249_999, "#C9190C"),
    (250_000, "#F00008"),
    (1_000_000, "#F00008"),
    (-5, "#4CAF50"),
]


@pytest.mark.parametrize("tokens,expected", CTX_BOUNDARIES)
def test_ctx_color_boundaries(tokens, expected):
    assert colors.ctx_color(tokens) == expected


def test_ctx_color_non_int_treated_as_zero():
    assert colors.ctx_color(None) == "#4CAF50"
    assert colors.ctx_color("lots") == "#4CAF50"


def test_ctx_colors_are_valid_hex():
    assert colors.CTX_COLORS[-1][0] is None, "last entry must be open-ended"
    for bound, hex_value in colors.CTX_COLORS:
        assert len(hex_value) == 7 and hex_value.startswith("#"), hex_value
        assert HEX.match(hex_value), hex_value
        r, g, b = colors.hex_to_rgb(hex_value)
        assert all(0 <= c <= 255 for c in (r, g, b))
