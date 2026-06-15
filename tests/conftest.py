"""Shared fixtures and builders for the engine tests."""

from __future__ import annotations

import pytest

from custom_components.shutter_engine.engine import (
    CoverCapabilities,
    DayMode,
    ModePosition,
    ProtectionFlags,
    ResolvedCoverConfig,
    ShadeType,
)


def make_cover_config(**overrides) -> ResolvedCoverConfig:
    """Create a fully-populated :class:`ResolvedCoverConfig` for tests.

    Defaults model a venetian blind that participates in wind and frost
    protection and can both position and tilt.
    """

    defaults = {
        "entity_id": "cover.test",
        "shade_type": ShadeType.VENETIAN,
        "protection": ProtectionFlags(wind=True, frost=True),
        "capabilities": CoverCapabilities(can_position=True, can_tilt=True),
        "mode_positions": {
            DayMode.SUN_PROTECTION: ModePosition(position=80, tilt=45),
            DayMode.ECO: ModePosition(position=80, tilt=45),
            DayMode.HEAT_PROTECTION: ModePosition(position=0, tilt=0),
        },
        "is_escape_route": True,
        "safe_position": 0,
        "ventilation_position": 10,
        "brightness_close": 40000.0,
        "brightness_open": 20000.0,
        "temp_hysteresis": 0.5,
        "azimuth_center": None,
        "azimuth_width": None,
        "azimuth_from": 90.0,
        "azimuth_to": 270.0,
        "elevation_min": 5.0,
        "elevation_max": 60.0,
        "delay_close": 0.0,
        "delay_open": 0.0,
        "min_movement_interval": 0.0,
        "sun_tracking_deadband": 5.0,
    }
    defaults.update(overrides)
    return ResolvedCoverConfig(**defaults)


@pytest.fixture
def cover_config() -> ResolvedCoverConfig:
    return make_cover_config()
