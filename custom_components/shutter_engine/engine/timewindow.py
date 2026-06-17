"""Night/morning time-window gating (concept section 6).

Both the night and the morning function only act inside a hard window
``[start, end]``. An optional relative trigger (sunrise/sunset + offset)
floats inside that frame::

    trigger_rel = clamp(sun_event + rel_offset, start, end)
    action_at   = min(
                      first_brightness_crossing_in_window,
                      trigger_rel,
                      end,            # "at the latest"
                  )
                + random(0..n)        # active with the holiday switch, capped at end
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class TimeWindowResult:
    """Outcome of a time-window evaluation for a single tick."""

    in_window: bool
    action_at: datetime
    action_due: bool


def _clamp(value: datetime, low: datetime, high: datetime) -> datetime:
    return max(low, min(value, high))


def resolve_time_window(
    now: datetime,
    window_start: datetime,
    window_end: datetime,
    *,
    sun_event: datetime | None = None,
    rel_offset: timedelta = timedelta(),
    brightness_crossing: datetime | None = None,
    random_offset: timedelta = timedelta(),
) -> TimeWindowResult:
    """Compute when the night/morning action is due for the current tick.

    Args:
        now: Current time.
        window_start: Earliest allowed action time.
        window_end: Latest enforced action time ("at the latest").
        sun_event: Sunrise (morning) or sunset (night) time, if available.
        rel_offset: Offset applied to ``sun_event``.
        brightness_crossing: Time at which the brightness threshold was first
            met within the window, if it already happened.
        random_offset: Extra randomized delay (holiday simulation), capped at
            ``window_end``.

    Returns:
        A :class:`TimeWindowResult` describing whether the window is open and
        whether the action is due now.
    """

    if window_end < window_start:
        raise ValueError("window_end must be >= window_start")

    candidates: list[datetime] = [window_end]
    if sun_event is not None:
        candidates.append(_clamp(sun_event + rel_offset, window_start, window_end))
    if brightness_crossing is not None and window_start <= brightness_crossing <= window_end:
        candidates.append(brightness_crossing)

    action_at = min(candidates) + random_offset
    action_at = min(action_at, window_end)

    in_window = window_start <= now <= window_end
    action_due = in_window and now >= action_at
    return TimeWindowResult(in_window=in_window, action_at=action_at, action_due=action_due)


def latch_night(
    previous: bool,
    *,
    night_action: bool,
    morning_action: bool,
    morning_window: bool,
) -> bool:
    """Persisted night latch for the night/blackout phase.

    The night and morning triggers from :func:`resolve_time_window` are momentary:
    they are only due *inside* their window. Without latching the night action
    falls away the moment ``now`` passes the window end, so a lower-priority day
    mode (e.g. eco) immediately reopens the cover. This latch remembers that night
    has fired and keeps it active until the morning trigger, so the cover stays
    closed across the window end, midnight and restarts.

    Args:
        previous: The latch state from the previous tick (restored across
            restarts).
        night_action: ``True`` when the night time-window action is due now.
        morning_action: ``True`` when the morning time-window action is due now.
        morning_window: ``True`` when a morning window is configured. Without one
            there is no defined reopen point, so the latch is disabled and the
            momentary ``night_action`` is returned — preserving the pre-latch
            behaviour where the day mode reopens after the night window closes.

    Returns:
        The new latch state.
    """

    if not morning_window:
        return night_action
    if morning_action:
        return False
    if night_action:
        return True
    return previous
