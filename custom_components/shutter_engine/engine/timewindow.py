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
