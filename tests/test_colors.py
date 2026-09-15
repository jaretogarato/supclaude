import re

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
