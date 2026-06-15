"""Tests for parsing the config-entry dictionary into engine dataclasses."""

from __future__ import annotations

from custom_components.shutter_engine.config import parse_config
from custom_components.shutter_engine.engine import DayMode, ShadeType
from custom_components.shutter_engine.engine.models import resolve_cover_config


def _sample() -> dict:
    return {
        "hub": {
            "sun_entity": "sun.sun",
            "weather_entity": "weather.home",
            "wind_entity": "binary_sensor.storm",
            "frost_entity": "binary_sensor.frost",
            "brightness_close": 40000,
            "brightness_open": 20000,
            "safe_position": 0,
        },
        "rooms": [
            {
                "name": "living",
                "day_mode": "sun_protection",
                "brightness_close": 35000,
                "night": {"enabled": True, "window_start": "20:00", "window_end": "23:00"},
                "areas": [
                    {
                        "name": "south",
                        "azimuth_from": 90,
                        "azimuth_to": 270,
                        "elevation_min": 5,
                        "elevation_max": 60,
                        "brightness_entity": "sensor.lux_south",
                        "contact_entity": "binary_sensor.door",
                        "is_escape_route": True,
                        "covers": [
                            {
                                "entity_id": "cover.living_south",
                                "shade_type": "venetian",
                                "mode_positions": {"sun_protection": {"position": 80, "tilt": 45}},
                                "brightness_close": 30000,
                            }
                        ],
                    }
                ],
            }
        ],
    }


def test_parse_config_structure() -> None:
    hub, rooms = parse_config(_sample())
    assert hub.sun_entity == "sun.sun"
    assert hub.brightness_close == 40000
    assert len(rooms) == 1

    room = rooms[0]
    assert room.name == "living"
    assert room.day_mode is DayMode.SUN_PROTECTION
    assert room.night.enabled is True
    assert len(room.areas) == 1

    area = room.areas[0]
    assert area.azimuth_from == 90
    assert area.is_escape_route is True
    assert len(area.covers) == 1

    cover = area.covers[0]
    assert cover.entity_id == "cover.living_south"
    assert cover.shade_type is ShadeType.VENETIAN
    assert cover.mode_positions[DayMode.SUN_PROTECTION].position == 80


def test_parse_config_inheritance_end_to_end() -> None:
    hub, rooms = parse_config(_sample())
    room = rooms[0]
    area = room.areas[0]
    cover = area.covers[0]

    resolved = resolve_cover_config(cover, area, room, hub)
    # brightness_close: cover(30000) wins over room(35000) and hub(40000).
    assert resolved.brightness_close == 30000
    # safe_position only set on hub.
    assert resolved.safe_position == 0
    # Venetian preset enables tilt.
    assert resolved.capabilities.can_tilt is True
    assert resolved.protection.wind is True
