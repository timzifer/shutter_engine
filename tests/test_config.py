"""Tests for assembling subentry dictionaries into engine dataclasses."""

from __future__ import annotations

from custom_components.shutter_engine.config import build_engine_state
from custom_components.shutter_engine.engine import DayMode, ShadeType


def _hub() -> dict:
    return {
        "sun_entity": "sun.sun",
        "weather_entity": "weather.home",
        "wind_entity": "binary_sensor.storm",
        "frost_entity": "binary_sensor.frost",
        "brightness_close": 40000,
        "brightness_open": 20000,
        "safe_position": 0,
    }


def _rulesets() -> dict:
    return {
        "rs1": {
            "name": "South facade",
            "brightness_close": 35000,
            "mode_positions": {"sun_protection": {"position": 80, "tilt": 45}},
            "night": {"enabled": True, "window_start": "20:00", "window_end": "23:00"},
        }
    }


def _controllers() -> dict:
    return {
        "ctrl1": {
            "area_id": "living",
            "name": "Living Room",
            "day_mode": "sun_protection",
            "ruleset_id": "rs1",
        }
    }


def _windows() -> dict:
    return {
        "win1": {
            "entity_id": "cover.living_south",
            "controller_id": "ctrl1",
            "shade_type": "venetian",
            "slat_tracking": False,
            "azimuth_from": 90,
            "azimuth_to": 270,
            "elevation_min": 5,
            "elevation_max": 60,
            "brightness_entity": "sensor.lux_south",
            "contact_entity": "binary_sensor.door",
            "is_escape_route": True,
            "brightness_close": 30000,
        }
    }


def test_build_engine_state_structure() -> None:
    state = build_engine_state(_hub(), _rulesets(), _controllers(), _windows())

    assert state.hub.sun_entity == "sun.sun"
    assert state.hub.brightness_close == 40000

    assert set(state.controllers) == {"ctrl1"}
    controller = state.controllers["ctrl1"]
    assert controller.config.area_id == "living"
    assert controller.config.day_mode is DayMode.SUN_PROTECTION
    assert controller.night.enabled is True  # from the referenced ruleset

    assert len(state.windows) == 1
    window = state.windows[0]
    assert window.subentry_id == "win1"
    assert window.controller_id == "ctrl1"
    assert window.config.entity_id == "cover.living_south"
    assert window.config.shade_type is ShadeType.VENETIAN
    assert window.config.slat_tracking is False
    assert window.config.azimuth_from == 90
    assert window.brightness_entity == "sensor.lux_south"
    assert window.night.enabled is True


def test_layered_inheritance_end_to_end() -> None:
    state = build_engine_state(_hub(), _rulesets(), _controllers(), _windows())
    resolved = state.windows[0].config
    # brightness_close: window(30000) wins over ruleset(35000) and hub(40000).
    assert resolved.brightness_close == 30000
    # safe_position only set on hub.
    assert resolved.safe_position == 0
    # mode positions come from the ruleset.
    assert resolved.mode_positions[DayMode.SUN_PROTECTION].position == 80
    # Venetian preset enables tilt and wind protection.
    assert resolved.capabilities.can_tilt is True
    assert resolved.protection.wind is True


def test_missing_ruleset_falls_back_to_hub_defaults() -> None:
    controllers = {"ctrl1": {"area_id": "living", "ruleset_id": "does_not_exist"}}
    windows = {"win1": {"entity_id": "cover.x", "controller_id": "ctrl1"}}
    state = build_engine_state(_hub(), {}, controllers, windows)
    resolved = state.windows[0].config
    # No ruleset -> hub brightness_close wins, mode positions empty.
    assert resolved.brightness_close == 40000
    assert resolved.mode_positions == {}
    assert state.controllers["ctrl1"].night.enabled is False


def test_window_with_dangling_controller_is_skipped() -> None:
    windows = {"win1": {"entity_id": "cover.x", "controller_id": "ghost"}}
    state = build_engine_state(_hub(), {}, {}, windows)
    assert state.windows == []
