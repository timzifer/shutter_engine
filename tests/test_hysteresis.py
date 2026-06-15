"""Tests for the hysteresis helpers."""

from __future__ import annotations

import pytest

from custom_components.shutter_engine.engine import Hysteresis, TemperatureHysteresis


def test_brightness_hysteresis_turns_on_at_high_threshold() -> None:
    hyst = Hysteresis(high=40000, low=20000)
    assert hyst.update(30000) is False  # between thresholds, stays off
    assert hyst.update(40000) is True  # reaches high -> on
    assert hyst.update(30000) is True  # between thresholds, stays on
    assert hyst.update(19999) is False  # below low -> off


def test_brightness_hysteresis_does_not_flutter() -> None:
    hyst = Hysteresis(high=40000, low=20000, active=True)
    # Oscillating around the high threshold must not toggle the state.
    for value in (39000, 41000, 38000, 42000):
        assert hyst.update(value) is True


def test_hysteresis_rejects_inverted_thresholds() -> None:
    with pytest.raises(ValueError):
        Hysteresis(high=10, low=20)


def test_temperature_hysteresis_around_set_point() -> None:
    hyst = TemperatureHysteresis(set_point=21.0, hysteresis=0.5)
    assert hyst.update(20.0) is False
    assert hyst.update(21.0) is True  # reached set point
    assert hyst.update(20.7) is True  # within hysteresis band, stays on
    assert hyst.update(20.4) is False  # below set_point - hysteresis
