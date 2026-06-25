"""Render a simulated scenario into a three-panel PNG chart.

Imported lazily by the test *after* ``pytest.importorskip("matplotlib")`` so the
core test suite still runs when matplotlib is not installed.

Layout (shared time axis, 0–24 h):

1. **Environment** — sun elevation (left axis) and indoor temperature (right
   axis).
2. **States** — discrete event/condition lanes (sun in funnel, bright enough,
   lock, fire, burglary …) drawn as filled bands while active.
3. **Output** — the resolver output: cover position and slat tilt, with the
   decision reason shown as coloured background bands.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless backend, no display needed

import matplotlib.pyplot as plt  # noqa: E402  (must follow backend selection)
from matplotlib.patches import Patch  # noqa: E402

from tests.visual.simulation import Frame, Scenario

#: Stable colour per decision reason so charts are comparable across scenarios.
_REASON_COLORS = {
    "hold": "#cfd8dc",
    "sun_protection": "#ffe082",
    "eco": "#c5e1a5",
    "heat_protection": "#ef9a9a",
    "night": "#9fa8da",
    "morning": "#80deea",
    "locked": "#bcaaa4",
    "disabled": "#e0e0e0",
    "fire": "#ff5252",
    "burglary": "#ce93d8",
    "storm": "#90a4ae",
    "frost_block": "#81d4fa",
    "lockout_open": "#a5d6a7",
    "lockout_ventilation": "#dce775",
    "min_interval_block": "#f0f0f0",
}

#: Discrete lanes for the middle panel: (attribute, label).
_STATE_LANES = (
    ("sun_in_funnel", "sun in funnel"),
    ("bright_enough", "bright enough"),
    ("heat_over_max", "over max temp"),
    ("locked", "locked"),
    ("fire_active", "fire"),
    ("burglary_active", "burglary"),
)


def _hours(frames: list[Frame]) -> list[float]:
    return [f.minute / 60.0 for f in frames]


def _reason_segments(frames: list[Frame]) -> list[tuple[float, float, str]]:
    """Collapse consecutive equal reasons into ``(start_h, end_h, reason)``."""

    segments: list[tuple[float, float, str]] = []
    start = frames[0].minute
    reason = frames[0].reason
    for _prev, cur in zip(frames, frames[1:], strict=False):
        if cur.reason != reason:
            segments.append((start / 60.0, cur.minute / 60.0, reason))
            start = cur.minute
            reason = cur.reason
    segments.append((start / 60.0, (frames[-1].minute + 1) / 60.0, reason))
    return segments


def render_scenario(frames: list[Frame], scenario: Scenario, out_path: Path) -> Path:
    """Render ``frames`` for ``scenario`` and save a PNG to ``out_path``."""

    hours = _hours(frames)
    fig, (ax_env, ax_state, ax_out) = plt.subplots(
        3,
        1,
        figsize=(11, 9),
        sharex=True,
        gridspec_kw={"height_ratios": [2, 2, 3], "hspace": 0.12},
    )
    fig.suptitle(scenario.title, fontsize=14, fontweight="bold")

    # -- Panel 1: environment ------------------------------------------------
    ax_env.plot(hours, [f.elevation for f in frames], color="#fb8c00", label="sun elevation (°)")
    ax_env.axhline(0.0, color="#bbbbbb", lw=0.8, ls=":")
    ax_env.set_ylabel("Elevation (°)", color="#fb8c00")
    ax_env.tick_params(axis="y", labelcolor="#fb8c00")
    ax_env.set_ylim(-10, 90)

    ax_temp = ax_env.twinx()
    ax_temp.plot(hours, [f.room_temp for f in frames], color="#e53935", label="indoor temp. (°C)")
    ax_temp.set_ylabel("Temperature (°C)", color="#e53935")
    ax_temp.tick_params(axis="y", labelcolor="#e53935")

    lines = ax_env.get_lines()[:1] + ax_temp.get_lines()
    ax_env.legend(lines, [ln.get_label() for ln in lines], loc="upper left", fontsize=8)
    ax_env.set_title("Environment: sun position & indoor temperature", fontsize=9, loc="left")

    # -- Panel 2: discrete state lanes --------------------------------------
    lane_labels: list[str] = []
    for idx, (attr, label) in enumerate(_STATE_LANES):
        active = [bool(getattr(f, attr)) for f in frames]
        if not any(active):
            label += " (—)"
        base = idx
        ax_state.fill_between(
            hours,
            base + 0.1,
            [base + 0.9 if a else base + 0.1 for a in active],
            step="post",
            color="#42a5f5",
            alpha=0.7,
            linewidth=0,
        )
        lane_labels.append(label)
    ax_state.set_yticks([i + 0.5 for i in range(len(_STATE_LANES))])
    ax_state.set_yticklabels(lane_labels, fontsize=8)
    ax_state.set_ylim(0, len(_STATE_LANES))
    ax_state.set_title("States & events (entity states)", fontsize=9, loc="left")
    ax_state.grid(True, axis="x", ls=":", alpha=0.4)

    # -- Panel 3: resolver output -------------------------------------------
    seen_reasons: list[str] = []
    for start_h, end_h, reason in _reason_segments(frames):
        ax_out.axvspan(
            start_h, end_h, color=_REASON_COLORS.get(reason, "#eeeeee"), alpha=0.5, linewidth=0
        )
        if reason not in seen_reasons:
            seen_reasons.append(reason)

    ax_out.plot(
        hours,
        [f.position for f in frames],
        color="#1e88e5",
        lw=2.0,
        drawstyle="steps-post",
        label="cover position (%)",
    )
    tilts = [f.tilt for f in frames]
    if any(t is not None for t in tilts):
        ax_out.plot(
            hours,
            [0 if t is None else t for t in tilts],
            color="#6d4c41",
            lw=1.3,
            ls="--",
            drawstyle="steps-post",
            label="slat tilt (%)",
        )
    ax_out.set_ylim(-5, 105)
    ax_out.set_ylabel("Position / tilt (%)")
    ax_out.set_xlabel("Time of day (hours)")
    ax_out.set_title("Output: cover position & decision reason", fontsize=9, loc="left")
    ax_out.grid(True, ls=":", alpha=0.4)

    reason_handles = [
        Patch(facecolor=_REASON_COLORS.get(r, "#eeeeee"), alpha=0.5, label=r) for r in seen_reasons
    ]
    output_handles = ax_out.get_legend_handles_labels()[0]
    ax_out.legend(
        output_handles + reason_handles,
        [h.get_label() for h in output_handles] + seen_reasons,
        loc="upper left",
        fontsize=8,
        ncol=2,
    )

    ax_out.set_xlim(0, 24)
    ax_out.set_xticks(range(0, 25, 3))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out_path
