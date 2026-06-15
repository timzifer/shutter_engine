"""Tests for the pure sun-geometry helpers."""

from __future__ import annotations

import pytest

from custom_components.shutter_engine.engine import (
    estimate_brightness,
    in_azimuth_funnel,
    in_elevation_band,
    in_sun_funnel,
)


def test_azimuth_funnel_normal_arc() -> None:
    assert in_azimuth_funnel(180, 90, 270) is True
    assert in_azimuth_funnel(80, 90, 270) is False
    assert in_azimuth_funnel(280, 90, 270) is False


def test_azimuth_funnel_wraparound_north() -> None:
    # Funnel spanning north (350 -> 20).
    assert in_azimuth_funnel(355, 350, 20) is True
    assert in_azimuth_funnel(10, 350, 20) is True
    assert in_azimuth_funnel(180, 350, 20) is False


def test_elevation_band() -> None:
    assert in_elevation_band(30, 5, 60) is True
    assert in_elevation_band(2, 5, 60) is False
    assert in_elevation_band(70, 5, 60) is False
    assert in_elevation_band(70, None, None) is True


def test_sun_funnel_combines_azimuth_and_elevation() -> None:
    assert in_sun_funnel(180, 30, 90, 270, 5, 60) is True
    assert in_sun_funnel(180, 70, 90, 270, 5, 60) is False  # too high
    assert in_sun_funnel(10, 30, 90, 270, 5, 60) is False  # outside azimuth


def test_estimate_brightness_below_horizon_is_zero() -> None:
    assert estimate_brightness(-5, 0.0) == 0.0


def test_estimate_brightness_scales_with_elevation() -> None:
    low = estimate_brightness(10, 0.0)
    high = estimate_brightness(60, 0.0)
    assert high > low > 0


def test_estimate_brightness_attenuated_by_clouds() -> None:
    clear = estimate_brightness(45, 0.0)
    overcast = estimate_brightness(45, 1.0)
    assert overcast < clear
    assert overcast == pytest.approx(clear * 0.2)
