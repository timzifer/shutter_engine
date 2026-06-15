"""Tests for the configuration data model and inheritance."""

from __future__ import annotations

from custom_components.shutter_engine.engine import (
    AreaConfig,
    CoverCapabilities,
    CoverConfig,
    HubConfig,
    ProtectionFlags,
    RoomConfig,
    ShadeType,
)
from custom_components.shutter_engine.engine.models import (
    presets_for,
    resolve_cover_config,
)


def test_shade_type_presets() -> None:
    venetian_protection, venetian_caps = presets_for(ShadeType.VENETIAN)
    assert venetian_protection == ProtectionFlags(wind=True, frost=True)
    assert venetian_caps == CoverCapabilities(can_position=True, can_tilt=True)

    roller_protection, roller_caps = presets_for(ShadeType.ROLLER_SHUTTER)
    assert roller_protection == ProtectionFlags(wind=False, frost=False)
    assert roller_caps == CoverCapabilities(can_position=True, can_tilt=False)


def test_deepest_value_wins() -> None:
    hub = HubConfig(brightness_close=40000, safe_position=0)
    room = RoomConfig(brightness_close=35000)
    area = AreaConfig(azimuth_from=90, azimuth_to=270)
    cover = CoverConfig(entity_id="cover.x", brightness_close=30000)

    resolved = resolve_cover_config(cover, area, room, hub)
    # Cover overrides room overrides hub.
    assert resolved.brightness_close == 30000
    # Falls back to hub when not set deeper.
    assert resolved.safe_position == 0


def test_inheritance_falls_back_through_levels() -> None:
    hub = HubConfig(temp_hysteresis=0.5)
    room = RoomConfig()
    area = AreaConfig()
    cover = CoverConfig(entity_id="cover.x")

    resolved = resolve_cover_config(cover, area, room, hub)
    assert resolved.temp_hysteresis == 0.5  # only set on hub


def test_hard_defaults_when_unset_everywhere() -> None:
    resolved = resolve_cover_config(
        CoverConfig(entity_id="cover.x"),
        AreaConfig(),
        RoomConfig(),
        HubConfig(),
    )
    assert resolved.ventilation_position == 10
    assert resolved.min_movement_interval == 0.0


def test_shade_type_seeds_protection_but_override_wins() -> None:
    # Venetian normally participates in wind/frost; an explicit override sticks.
    cover = CoverConfig(
        entity_id="cover.x",
        shade_type=ShadeType.VENETIAN,
        protection=ProtectionFlags(wind=False, frost=False),
    )
    resolved = resolve_cover_config(cover, AreaConfig(), RoomConfig(), HubConfig())
    assert resolved.protection == ProtectionFlags(wind=False, frost=False)


def test_shade_type_seeds_capabilities_when_not_overridden() -> None:
    cover = CoverConfig(entity_id="cover.x", shade_type=ShadeType.ROLLER_SHUTTER)
    resolved = resolve_cover_config(cover, AreaConfig(), RoomConfig(), HubConfig())
    assert resolved.capabilities == CoverCapabilities(can_position=True, can_tilt=False)


def test_escape_route_propagated_from_area() -> None:
    resolved = resolve_cover_config(
        CoverConfig(entity_id="cover.x"),
        AreaConfig(is_escape_route=False),
        RoomConfig(),
        HubConfig(),
    )
    assert resolved.is_escape_route is False
