"""Tests for the configuration data model and inheritance."""

from __future__ import annotations

from custom_components.shutter_engine.engine import (
    ControllerConfig,
    CoverCapabilities,
    HubConfig,
    ProtectionFlags,
    RulesetConfig,
    ShadeType,
    WindowConfig,
)
from custom_components.shutter_engine.engine.models import (
    presets_for,
    resolve_window,
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
    ruleset = RulesetConfig(brightness_close=35000)
    controller = ControllerConfig()
    window = WindowConfig(entity_id="cover.x", brightness_close=30000)

    resolved = resolve_window(window, controller, ruleset, hub)
    # Window overrides ruleset overrides hub.
    assert resolved.brightness_close == 30000
    # Falls back to hub when not set deeper.
    assert resolved.safe_position == 0


def test_inheritance_falls_back_through_levels() -> None:
    hub = HubConfig(temp_hysteresis=0.5)
    resolved = resolve_window(
        WindowConfig(entity_id="cover.x"),
        ControllerConfig(),
        RulesetConfig(),
        hub,
    )
    assert resolved.temp_hysteresis == 0.5  # only set on hub


def test_hard_defaults_when_unset_everywhere() -> None:
    resolved = resolve_window(
        WindowConfig(entity_id="cover.x"),
        ControllerConfig(),
        RulesetConfig(),
        HubConfig(),
    )
    assert resolved.ventilation_position == 10
    assert resolved.min_movement_interval == 0.0


def test_shade_type_seeds_protection_but_override_wins() -> None:
    # Venetian normally participates in wind/frost; an explicit override sticks.
    window = WindowConfig(
        entity_id="cover.x",
        shade_type=ShadeType.VENETIAN,
        protection=ProtectionFlags(wind=False, frost=False),
    )
    resolved = resolve_window(window, ControllerConfig(), RulesetConfig(), HubConfig())
    assert resolved.protection == ProtectionFlags(wind=False, frost=False)


def test_shade_type_seeds_capabilities_when_not_overridden() -> None:
    window = WindowConfig(entity_id="cover.x", shade_type=ShadeType.ROLLER_SHUTTER)
    resolved = resolve_window(window, ControllerConfig(), RulesetConfig(), HubConfig())
    assert resolved.capabilities == CoverCapabilities(can_position=True, can_tilt=False)


def test_slat_tracking_defaults_on_for_venetian() -> None:
    window = WindowConfig(entity_id="cover.x", shade_type=ShadeType.VENETIAN)
    resolved = resolve_window(window, ControllerConfig(), RulesetConfig(), HubConfig())
    assert resolved.slat_tracking is True


def test_slat_tracking_defaults_off_for_roller_shutter() -> None:
    window = WindowConfig(entity_id="cover.x", shade_type=ShadeType.ROLLER_SHUTTER)
    resolved = resolve_window(window, ControllerConfig(), RulesetConfig(), HubConfig())
    assert resolved.slat_tracking is False


def test_slat_tracking_explicit_override_wins() -> None:
    window = WindowConfig(entity_id="cover.x", shade_type=ShadeType.VENETIAN, slat_tracking=False)
    resolved = resolve_window(window, ControllerConfig(), RulesetConfig(), HubConfig())
    assert resolved.slat_tracking is False


def test_escape_route_propagated_from_window() -> None:
    resolved = resolve_window(
        WindowConfig(entity_id="cover.x", is_escape_route=False),
        ControllerConfig(),
        RulesetConfig(),
        HubConfig(),
    )
    assert resolved.is_escape_route is False


def test_mode_positions_from_ruleset_overridden_per_window() -> None:
    from custom_components.shutter_engine.engine import DayMode, ModePosition

    ruleset = RulesetConfig(
        mode_positions={
            DayMode.SUN_PROTECTION: ModePosition(position=80, tilt=45),
            DayMode.ECO: ModePosition(position=70),
        }
    )
    window = WindowConfig(
        entity_id="cover.x",
        mode_positions={DayMode.SUN_PROTECTION: ModePosition(position=60, tilt=30)},
    )
    resolved = resolve_window(window, ControllerConfig(), ruleset, HubConfig())
    # Window overrides the sun-protection target, eco falls back to the ruleset.
    assert resolved.mode_positions[DayMode.SUN_PROTECTION] == ModePosition(position=60, tilt=30)
    assert resolved.mode_positions[DayMode.ECO] == ModePosition(position=70)
