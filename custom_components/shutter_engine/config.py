"""Parsing of the stored config-entry dictionary into engine dataclasses.

This module is pure Python (no Home Assistant import) so the config schema can
be unit-tested in isolation. The config flow produces the dictionary; the
coordinator consumes the parsed dataclasses.
"""

from __future__ import annotations

from typing import Any

from .engine import (
    AreaConfig,
    CoverCapabilities,
    CoverConfig,
    DayMode,
    HubConfig,
    ModePosition,
    ProtectionFlags,
    RoomConfig,
    ShadeType,
)
from .engine.models import TimeFunction

# Inheritable scalar keys shared by every level.
_INHERITABLE_KEYS = (
    "safe_position",
    "ventilation_position",
    "brightness_close",
    "brightness_open",
    "temp_hysteresis",
    "azimuth_center",
    "azimuth_width",
    "elevation_min",
    "elevation_max",
    "delay_close",
    "delay_open",
    "min_movement_interval",
    "sun_tracking_deadband",
)


def _inheritable(data: dict[str, Any]) -> dict[str, Any]:
    return {key: data.get(key) for key in _INHERITABLE_KEYS}


def _parse_time_function(data: dict[str, Any] | None) -> TimeFunction:
    data = data or {}
    return TimeFunction(
        enabled=bool(data.get("enabled", False)),
        window_start=data.get("window_start"),
        window_end=data.get("window_end"),
        rel_offset=data.get("rel_offset"),
        random_max=float(data.get("random_max", 0.0)),
        weekend_coupling=bool(data.get("weekend_coupling", False)),
    )


def _parse_mode_positions(data: dict[str, Any] | None) -> dict[DayMode, ModePosition]:
    result: dict[DayMode, ModePosition] = {}
    for key, value in (data or {}).items():
        mode = DayMode(key)
        result[mode] = ModePosition(
            position=int(value["position"]),
            tilt=value.get("tilt"),
        )
    return result


def _parse_cover(data: dict[str, Any]) -> CoverConfig:
    protection = None
    if "protection" in data:
        protection = ProtectionFlags(
            wind=bool(data["protection"].get("wind", False)),
            frost=bool(data["protection"].get("frost", False)),
        )
    capabilities = None
    if "capabilities" in data:
        capabilities = CoverCapabilities(
            can_position=bool(data["capabilities"].get("can_position", True)),
            can_tilt=bool(data["capabilities"].get("can_tilt", False)),
        )
    slat_tracking = data.get("slat_tracking")
    if slat_tracking is not None:
        slat_tracking = bool(slat_tracking)
    return CoverConfig(
        entity_id=data["entity_id"],
        shade_type=ShadeType(data.get("shade_type", ShadeType.STANDARD.value)),
        protection=protection,
        capabilities=capabilities,
        slat_tracking=slat_tracking,
        mode_positions=_parse_mode_positions(data.get("mode_positions")),
        **_inheritable(data),
    )


def _parse_area(data: dict[str, Any]) -> AreaConfig:
    return AreaConfig(
        name=data.get("name", ""),
        azimuth_from=data.get("azimuth_from"),
        azimuth_to=data.get("azimuth_to"),
        brightness_entity=data.get("brightness_entity"),
        contact_entity=data.get("contact_entity"),
        is_escape_route=bool(data.get("is_escape_route", True)),
        covers=[_parse_cover(c) for c in data.get("covers", [])],
        **_inheritable(data),
    )


def _parse_room(data: dict[str, Any]) -> RoomConfig:
    return RoomConfig(
        area_id=data.get("area_id", ""),
        name=data.get("name", ""),
        day_mode=DayMode(data.get("day_mode", DayMode.OFF.value)),
        locked=bool(data.get("locked", False)),
        holiday=bool(data.get("holiday", False)),
        heating_entity=data.get("heating_entity"),
        target_temp=data.get("target_temp"),
        room_temp_entity=data.get("room_temp_entity"),
        max_temp=data.get("max_temp"),
        night=_parse_time_function(data.get("night")),
        morning=_parse_time_function(data.get("morning")),
        areas=[_parse_area(a) for a in data.get("areas", [])],
        **_inheritable(data),
    )


def parse_hub(data: dict[str, Any]) -> HubConfig:
    """Parse the hub section of the config dictionary."""

    return HubConfig(
        sun_entity=data.get("sun_entity"),
        weather_entity=data.get("weather_entity"),
        workday_entity=data.get("workday_entity"),
        wind_entity=data.get("wind_entity"),
        frost_entity=data.get("frost_entity"),
        fire_entity=data.get("fire_entity"),
        burglary_entity=data.get("burglary_entity"),
        **_inheritable(data),
    )


def parse_config(data: dict[str, Any]) -> tuple[HubConfig, list[RoomConfig]]:
    """Parse the full config dictionary into ``(hub, rooms)``."""

    hub = parse_hub(data.get("hub", {}))
    rooms = [_parse_room(r) for r in data.get("rooms", [])]
    return hub, rooms
