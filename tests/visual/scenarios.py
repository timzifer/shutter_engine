"""Concrete visual scenarios over a synthetic day.

Each scenario shares the same one-minute sun arc and indoor-temperature curve
from :mod:`tests.visual.simulation` and injects the events the user asked to see
documented: sun position, indoor temperature, manual lock, fire and burglary.
"""

from __future__ import annotations

from custom_components.shutter_engine.engine import DayMode
from tests.visual.simulation import (
    ControllerParams,
    RawInput,
    Scenario,
    build_day,
)


def _h(hour: float) -> int:
    """Minutes since midnight for a clock hour (e.g. ``13.5`` -> 13:30)."""

    return int(hour * 60)


# ---------------------------------------------------------------------------
# 1. Sun protection over a clear day
# ---------------------------------------------------------------------------

SUN_PROTECTION_DAY = Scenario(
    name="sun_protection_day",
    title="Sun protection on a clear day",
    description=(
        "Day mode sun protection. As soon as the sun enters the funnel and it is "
        "bright enough, the driver shades to 80 %; the slats track the sun "
        "elevation. In the evening, when the brightness drops below the lower "
        "hysteresis threshold, the cover opens again."
    ),
    controller=ControllerParams(day_mode=DayMode.SUN_PROTECTION),
    inputs=build_day(),
)


# ---------------------------------------------------------------------------
# 2. Heat protection on a hot day
# ---------------------------------------------------------------------------

HEAT_PROTECTION_HOT_DAY = Scenario(
    name="heat_protection_hot_day",
    title="Heat protection on a hot day",
    description=(
        "Day mode heat protection with a maximum temperature of 24 °C. Over the "
        "day the room temperature climbs; as soon as it exceeds 24 °C (or the sun "
        "directly shades), the cover closes fully (0 %) for active cooling. Once "
        "the room cools down, it opens again."
    ),
    controller=ControllerParams(day_mode=DayMode.HEAT_PROTECTION, max_temp=24.0),
    inputs=build_day(base_temp=21.0, temp_swing=8.0),
)


# ---------------------------------------------------------------------------
# 3. Manual lock suppresses automation
# ---------------------------------------------------------------------------


def _lock_window(raw: RawInput) -> RawInput:
    # Lock from 07:30 to 13:00 — across the morning shading window.
    if _h(7.5) <= raw.minute < _h(13):
        raw.locked = True
    return raw


MANUAL_LOCK = Scenario(
    name="manual_lock",
    title="Manual lock holds the position",
    description=(
        "Day mode sun protection, but the manual lock is active from 07:30 to "
        "13:00. Even though the sun and brightness would have long triggered "
        "shading, the cover holds its position (reason LOCKED). Only after the "
        "lock is released at 13:00 does the automation shade to 80 %."
    ),
    controller=ControllerParams(day_mode=DayMode.SUN_PROTECTION),
    inputs=build_day(_lock_window),
)


# ---------------------------------------------------------------------------
# 4. Fire forces the escape route fully open
# ---------------------------------------------------------------------------


def _fire_window(raw: RawInput) -> RawInput:
    # Short fire/smoke alarm around 13:00.
    if _h(13) <= raw.minute < _h(13.5):
        raw.fire_active = True
    return raw


FIRE_ESCAPE = Scenario(
    name="fire_escape",
    title="Fire opens the escape route",
    description=(
        "Day mode sun protection, the cover is shaded at midday. A short fire "
        "alarm (13:00–13:30) immediately drives the cover marked as an escape "
        "route fully open (100 %, reason FIRE), breaking all constraints. After "
        "the alarm the automation returns to sun protection."
    ),
    controller=ControllerParams(day_mode=DayMode.SUN_PROTECTION),
    inputs=build_day(_fire_window),
)


# ---------------------------------------------------------------------------
# 5. Burglary drives to a fixed security position
# ---------------------------------------------------------------------------


def _burglary_window(raw: RawInput) -> RawInput:
    # Intrusion detected in the late evening (21:00–23:00).
    if _h(21) <= raw.minute < _h(23):
        raw.burglary_active = True
    return raw


BURGLARY = Scenario(
    name="burglary",
    title="Burglary drives to the security position",
    description=(
        "Day mode sun protection. In the evening (21:00–23:00) the burglary "
        "monitoring reports an alarm; the safety driver moves the cover to the "
        "configured burglary position (here 0 %, fully closed, reason BURGLARY) "
        "and enforces it. After the alarm the day automation takes over again."
    ),
    controller=ControllerParams(day_mode=DayMode.SUN_PROTECTION, burglary_position=0),
    inputs=build_day(_burglary_window),
)


#: All scenarios, in documentation order.
SCENARIOS: tuple[Scenario, ...] = (
    SUN_PROTECTION_DAY,
    HEAT_PROTECTION_HOT_DAY,
    MANUAL_LOCK,
    FIRE_ESCAPE,
    BURGLARY,
)
