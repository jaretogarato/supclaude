"""Color Authority. Every color in SupClaude comes from here.

Change a hex value here and both the dashboard and the iTerm2 tab colors follow.
"""

STATES = ("working", "needs_you", "done", "agents", "idle")

COLORS = {
    "working": "#3B82F6",    # blue
    "needs_you": "#FF69B4",  # hot pink
    "done": "#22C55E",       # green
    "agents": "#EAB308",     # yellow
    "idle": "#6B7280",       # gray
}

LABELS = {
    "working": "WORKING",
    "needs_you": "NEEDS YOU",
    "done": "DONE",
    "agents": "AGENTS",
    "idle": "IDLE",
}

# Lower number sorts higher in the dashboard.
SORT_ORDER = {
    "needs_you": 0,
    "done": 1,
    "working": 2,
    "agents": 3,
    "idle": 4,
}


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
