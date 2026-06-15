"""Tests for the dynamic venetian slat-tracking geometry."""

from __future__ import annotations

from custom_components.shutter_engine.engine import (
    apply_tilt_deadband,
    slat_tilt_for_elevation,
)

# ---------------------------------------------------------------------------
# Elevation -> tilt mapping
# ---------------------------------------------------------------------------


def test_low_sun_closes_slats() -> None:
    assert slat_tilt_for_elevation(0.0) == 0


def test_high_sun_opens_slats() -> None:
    assert slat_tilt_for_elevation(90.0) == 100


def test_midpoint_interpolates_linearly() -> None:
    assert slat_tilt_for_elevation(45.0) == 50


def test_clamped_below_and_above_band() -> None:
    assert slat_tilt_for_elevation(-10.0) == 0
    assert slat_tilt_for_elevation(120.0) == 100


def test_custom_elevation_band() -> None:
    # Tracking domain restricted to the area's funnel band.
    assert slat_tilt_for_elevation(5.0, elevation_low=5.0, elevation_high=65.0) == 0
    assert slat_tilt_for_elevation(65.0, elevation_low=5.0, elevation_high=65.0) == 100
    assert slat_tilt_for_elevation(35.0, elevation_low=5.0, elevation_high=65.0) == 50


def test_degenerate_band_returns_closed() -> None:
    assert slat_tilt_for_elevation(30.0, elevation_low=50.0, elevation_high=50.0) == 0


# ---------------------------------------------------------------------------
# Dead band
# ---------------------------------------------------------------------------


def test_deadband_suppresses_small_change() -> None:
    # 42 vs 45 is within the 5pt dead band -> keep current.
    assert apply_tilt_deadband(42, 45, 5.0) == 45


def test_deadband_allows_large_change() -> None:
    assert apply_tilt_deadband(60, 45, 5.0) == 60


def test_deadband_change_at_threshold_moves() -> None:
    # Exactly at the dead band is not "within" it -> move.
    assert apply_tilt_deadband(50, 45, 5.0) == 50


def test_deadband_with_unknown_current_returns_target() -> None:
    assert apply_tilt_deadband(30, None, 5.0) == 30


def test_zero_deadband_always_moves() -> None:
    assert apply_tilt_deadband(46, 45, 0.0) == 46
