"""Tests for the night/morning time-window gating."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.shutter_engine.engine import latch_night, resolve_time_window


def _dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 6, 15, hour, minute)


def test_action_clamped_to_window_start() -> None:
    # Sunrise at 05:00 is earlier than the 06:30 window start -> clamp up.
    result = resolve_time_window(
        now=_dt(6, 45),
        window_start=_dt(6, 30),
        window_end=_dt(9, 0),
        sun_event=_dt(5, 0),
    )
    assert result.action_at == _dt(6, 30)
    assert result.in_window is True
    assert result.action_due is True


def test_latest_enforced_at_window_end() -> None:
    # No sun event, no brightness crossing -> action forced at window end.
    result = resolve_time_window(
        now=_dt(8, 0),
        window_start=_dt(6, 30),
        window_end=_dt(9, 0),
    )
    assert result.action_at == _dt(9, 0)
    assert result.action_due is False  # 08:00 is before the enforced 09:00


def test_brightness_crossing_wins_when_earliest() -> None:
    result = resolve_time_window(
        now=_dt(7, 30),
        window_start=_dt(6, 30),
        window_end=_dt(9, 0),
        sun_event=_dt(8, 0),
        brightness_crossing=_dt(7, 15),
    )
    assert result.action_at == _dt(7, 15)
    assert result.action_due is True


def test_brightness_crossing_outside_window_ignored() -> None:
    result = resolve_time_window(
        now=_dt(7, 0),
        window_start=_dt(6, 30),
        window_end=_dt(9, 0),
        sun_event=_dt(8, 0),
        brightness_crossing=_dt(5, 0),  # before window -> ignored
    )
    assert result.action_at == _dt(8, 0)


def test_random_offset_capped_at_window_end() -> None:
    result = resolve_time_window(
        now=_dt(9, 0),
        window_start=_dt(6, 30),
        window_end=_dt(9, 0),
        sun_event=_dt(8, 50),
        random_offset=timedelta(minutes=30),
    )
    assert result.action_at == _dt(9, 0)


def test_not_in_window_is_not_due() -> None:
    result = resolve_time_window(
        now=_dt(10, 0),
        window_start=_dt(6, 30),
        window_end=_dt(9, 0),
    )
    assert result.in_window is False
    assert result.action_due is False


def test_invalid_window_raises() -> None:
    with pytest.raises(ValueError):
        resolve_time_window(now=_dt(8, 0), window_start=_dt(9, 0), window_end=_dt(6, 0))


# -- night latch ------------------------------------------------------------


def test_latch_sets_when_night_fires() -> None:
    assert latch_night(False, night_action=True, morning_action=False, morning_window=True) is True


def test_latch_holds_after_window_without_new_action() -> None:
    # Night already latched; window passed so no momentary action -> stays closed.
    assert latch_night(True, night_action=False, morning_action=False, morning_window=True) is True


def test_latch_clears_at_morning() -> None:
    assert latch_night(True, night_action=False, morning_action=True, morning_window=True) is False


def test_morning_wins_over_night_on_overlap() -> None:
    assert latch_night(True, night_action=True, morning_action=True, morning_window=True) is False


def test_no_morning_window_disables_latch() -> None:
    # Without a morning window there is no reopen point, so the latch is disabled
    # and the live (momentary) night action is returned: it sets on a night
    # action and falls back as soon as the action is gone, even if previously on.
    assert latch_night(False, night_action=True, morning_action=False, morning_window=False) is True
    assert (
        latch_night(True, night_action=False, morning_action=False, morning_window=False) is False
    )
