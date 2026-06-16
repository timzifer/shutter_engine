"""Tests for the resolver (priority ladder + constraints)."""

from __future__ import annotations

from custom_components.shutter_engine.engine import (
    ContactState,
    CoverCapabilities,
    DayMode,
    DecisionReason,
    ProtectionFlags,
    ResolverInput,
    resolve,
    resolve_trace,
)
from custom_components.shutter_engine.engine.const import (
    POSITION_CLOSED,
    POSITION_OPEN,
)

from .conftest import make_cover_config

# ---------------------------------------------------------------------------
# Driver ladder — first match wins
# ---------------------------------------------------------------------------


def test_fire_opens_escape_route_cover() -> None:
    inp = ResolverInput(config=make_cover_config(), fire_active=True, current_position=0)
    decision = resolve(inp)
    assert decision.position == POSITION_OPEN
    assert decision.reason is DecisionReason.FIRE


def test_fire_breaks_frost_and_min_interval() -> None:
    cfg = make_cover_config(min_movement_interval=300)
    inp = ResolverInput(
        config=cfg,
        fire_active=True,
        frost_active=True,
        seconds_since_last_move=1,
        current_position=0,
    )
    decision = resolve(inp)
    assert decision.position == POSITION_OPEN
    assert decision.reason is DecisionReason.FIRE
    assert decision.blocked is False


def test_fire_does_not_drive_non_escape_route_cover() -> None:
    cfg = make_cover_config(is_escape_route=False)
    inp = ResolverInput(
        config=cfg,
        fire_active=True,
        day_mode=DayMode.SUN_PROTECTION,
        sun_in_funnel=True,
        bright_enough=True,
    )
    decision = resolve(inp)
    # Falls through the ladder to sun protection.
    assert decision.reason is DecisionReason.SUN_PROTECTION


def test_burglary_default_holds_position() -> None:
    inp = ResolverInput(config=make_cover_config(), burglary_active=True, current_position=55)
    decision = resolve(inp)
    assert decision.position == 55
    assert decision.reason is DecisionReason.BURGLARY


def test_burglary_with_explicit_position() -> None:
    inp = ResolverInput(
        config=make_cover_config(),
        burglary_active=True,
        burglary_position=30,
        current_position=100,
    )
    decision = resolve(inp)
    assert decision.position == 30
    assert decision.reason is DecisionReason.BURGLARY


def test_storm_drives_to_safe_position_when_wind_protected() -> None:
    cfg = make_cover_config(safe_position=0, protection=ProtectionFlags(wind=True))
    inp = ResolverInput(config=cfg, storm_active=True, current_position=80)
    decision = resolve(inp)
    assert decision.position == 0
    assert decision.reason is DecisionReason.STORM


def test_storm_ignored_for_non_wind_cover() -> None:
    # A roller shutter (no wind participation) keeps shading in a storm.
    cfg = make_cover_config(protection=ProtectionFlags(wind=False))
    inp = ResolverInput(
        config=cfg,
        storm_active=True,
        day_mode=DayMode.SUN_PROTECTION,
        sun_in_funnel=True,
        bright_enough=True,
    )
    decision = resolve(inp)
    assert decision.reason is DecisionReason.SUN_PROTECTION


def test_lock_holds_position() -> None:
    inp = ResolverInput(config=make_cover_config(), locked=True, current_position=42)
    decision = resolve(inp)
    assert decision.position == 42
    assert decision.reason is DecisionReason.LOCKED


def test_manual_override_holds_position() -> None:
    inp = ResolverInput(config=make_cover_config(), manual_override=True, current_position=33)
    decision = resolve(inp)
    assert decision.position == 33
    assert decision.reason is DecisionReason.MANUAL_OVERRIDE


def test_morning_opens() -> None:
    inp = ResolverInput(config=make_cover_config(), morning_due=True, current_position=0)
    decision = resolve(inp)
    assert decision.position == POSITION_OPEN
    assert decision.reason is DecisionReason.MORNING


def test_night_closes() -> None:
    inp = ResolverInput(config=make_cover_config(), night_due=True, current_position=100)
    decision = resolve(inp)
    assert decision.position == POSITION_CLOSED
    assert decision.reason is DecisionReason.NIGHT


def test_morning_wins_over_night() -> None:
    inp = ResolverInput(config=make_cover_config(), morning_due=True, night_due=True)
    assert resolve(inp).reason is DecisionReason.MORNING


# ---------------------------------------------------------------------------
# Day modes
# ---------------------------------------------------------------------------


def test_sun_protection_shades_when_in_funnel_and_bright() -> None:
    inp = ResolverInput(
        config=make_cover_config(),
        day_mode=DayMode.SUN_PROTECTION,
        sun_in_funnel=True,
        bright_enough=True,
    )
    decision = resolve(inp)
    assert decision.position == 80
    assert decision.tilt == 45
    assert decision.reason is DecisionReason.SUN_PROTECTION


def test_sun_protection_opens_when_not_bright() -> None:
    inp = ResolverInput(
        config=make_cover_config(),
        day_mode=DayMode.SUN_PROTECTION,
        sun_in_funnel=True,
        bright_enough=False,
    )
    decision = resolve(inp)
    assert decision.position == POSITION_OPEN


def test_eco_stays_open_until_set_point_reached() -> None:
    inp = ResolverInput(
        config=make_cover_config(),
        day_mode=DayMode.ECO,
        sun_in_funnel=True,
        bright_enough=True,
        eco_temp_reached=False,
    )
    assert resolve(inp).position == POSITION_OPEN


def test_eco_shades_once_set_point_reached() -> None:
    inp = ResolverInput(
        config=make_cover_config(),
        day_mode=DayMode.ECO,
        sun_in_funnel=True,
        bright_enough=True,
        eco_temp_reached=True,
    )
    decision = resolve(inp)
    assert decision.position == 80
    assert decision.reason is DecisionReason.ECO


def test_heat_protection_closes_on_overheat_without_sun() -> None:
    inp = ResolverInput(
        config=make_cover_config(),
        day_mode=DayMode.HEAT_PROTECTION,
        sun_in_funnel=False,
        bright_enough=False,
        heat_over_max=True,
    )
    decision = resolve(inp)
    assert decision.position == POSITION_CLOSED
    assert decision.reason is DecisionReason.HEAT_PROTECTION


def test_off_mode_holds() -> None:
    inp = ResolverInput(config=make_cover_config(), day_mode=DayMode.OFF, current_position=77)
    decision = resolve(inp)
    assert decision.position == 77
    assert decision.reason is DecisionReason.HOLD


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------


def test_frost_blocks_movement() -> None:
    cfg = make_cover_config(protection=ProtectionFlags(frost=True))
    inp = ResolverInput(
        config=cfg,
        day_mode=DayMode.SUN_PROTECTION,
        sun_in_funnel=True,
        bright_enough=True,
        frost_active=True,
        current_position=100,
    )
    decision = resolve(inp)
    assert decision.position == 100  # held
    assert decision.reason is DecisionReason.FROST_BLOCK
    assert decision.blocked is True


def test_frost_has_priority_over_storm() -> None:
    # Frost wins: a frozen shutter must not move, even in a storm.
    cfg = make_cover_config(protection=ProtectionFlags(wind=True, frost=True))
    inp = ResolverInput(
        config=cfg,
        storm_active=True,
        frost_active=True,
        current_position=90,
    )
    decision = resolve(inp)
    assert decision.position == 90
    assert decision.reason is DecisionReason.FROST_BLOCK


def test_frost_ignored_when_cover_not_frost_protected() -> None:
    cfg = make_cover_config(protection=ProtectionFlags(wind=True, frost=False))
    inp = ResolverInput(
        config=cfg,
        storm_active=True,
        frost_active=True,
        current_position=90,
    )
    decision = resolve(inp)
    assert decision.reason is DecisionReason.STORM


def test_lockout_open_forces_full_open() -> None:
    inp = ResolverInput(
        config=make_cover_config(),
        day_mode=DayMode.SUN_PROTECTION,
        sun_in_funnel=True,
        bright_enough=True,
        contact_state=ContactState.OPEN,
        current_position=80,
    )
    decision = resolve(inp)
    assert decision.position == POSITION_OPEN
    assert decision.reason is DecisionReason.LOCKOUT_OPEN


def test_lockout_tilted_clamps_close_to_ventilation() -> None:
    cfg = make_cover_config(ventilation_position=10)
    inp = ResolverInput(
        config=cfg,
        night_due=True,  # wants to close to 0
        contact_state=ContactState.TILTED,
        current_position=100,
    )
    decision = resolve(inp)
    assert decision.position == 10
    assert decision.reason is DecisionReason.LOCKOUT_VENTILATION


def test_lockout_tilted_does_not_affect_open_command() -> None:
    cfg = make_cover_config(ventilation_position=10)
    inp = ResolverInput(
        config=cfg,
        morning_due=True,  # wants to open to 100
        contact_state=ContactState.TILTED,
    )
    decision = resolve(inp)
    assert decision.position == POSITION_OPEN
    assert decision.reason is DecisionReason.MORNING


def test_min_interval_blocks_repeated_move() -> None:
    cfg = make_cover_config(min_movement_interval=300)
    inp = ResolverInput(
        config=cfg,
        night_due=True,
        current_position=100,
        seconds_since_last_move=30,
    )
    decision = resolve(inp)
    assert decision.position == 100  # held
    assert decision.reason is DecisionReason.MIN_INTERVAL_BLOCK
    assert decision.blocked is True


def test_min_interval_allows_move_after_interval() -> None:
    cfg = make_cover_config(min_movement_interval=300)
    inp = ResolverInput(
        config=cfg,
        night_due=True,
        current_position=100,
        seconds_since_last_move=600,
    )
    decision = resolve(inp)
    assert decision.position == POSITION_CLOSED
    assert decision.reason is DecisionReason.NIGHT


def test_min_interval_does_not_block_when_already_at_target() -> None:
    cfg = make_cover_config(min_movement_interval=300)
    inp = ResolverInput(
        config=cfg,
        night_due=True,
        current_position=0,  # already closed
        seconds_since_last_move=5,
    )
    decision = resolve(inp)
    assert decision.reason is DecisionReason.NIGHT
    assert decision.blocked is False


# ---------------------------------------------------------------------------
# Capability mapping
# ---------------------------------------------------------------------------


def test_position_only_cover_maps_to_binary() -> None:
    cfg = make_cover_config(capabilities=CoverCapabilities(can_position=False, can_tilt=False))
    inp = ResolverInput(
        config=cfg,
        day_mode=DayMode.SUN_PROTECTION,
        sun_in_funnel=True,
        bright_enough=True,
    )
    decision = resolve(inp)
    # 80% shade -> binary "open" since pos > 0.
    assert decision.position == POSITION_OPEN
    assert decision.tilt is None


def test_tilt_dropped_when_unsupported() -> None:
    cfg = make_cover_config(capabilities=CoverCapabilities(can_position=True, can_tilt=False))
    inp = ResolverInput(
        config=cfg,
        day_mode=DayMode.SUN_PROTECTION,
        sun_in_funnel=True,
        bright_enough=True,
    )
    decision = resolve(inp)
    assert decision.position == 80
    assert decision.tilt is None


# ---------------------------------------------------------------------------
# Dynamic venetian slat tracking
# ---------------------------------------------------------------------------


def test_slat_tracking_overrides_static_tilt() -> None:
    inp = ResolverInput(
        config=make_cover_config(),  # venetian, slat_tracking on
        day_mode=DayMode.SUN_PROTECTION,
        sun_in_funnel=True,
        bright_enough=True,
        tracked_tilt=70,
        current_tilt=10,
    )
    decision = resolve(inp)
    assert decision.position == 80  # static shade position kept
    assert decision.tilt == 70  # dynamic tilt replaces the configured 45


def test_slat_tracking_honours_deadband() -> None:
    cfg = make_cover_config(sun_tracking_deadband=5.0)
    inp = ResolverInput(
        config=cfg,
        day_mode=DayMode.SUN_PROTECTION,
        sun_in_funnel=True,
        bright_enough=True,
        tracked_tilt=47,
        current_tilt=45,  # change of 2 < dead band -> held
    )
    assert resolve(inp).tilt == 45


def test_slat_tracking_disabled_keeps_static_tilt() -> None:
    cfg = make_cover_config(slat_tracking=False)
    inp = ResolverInput(
        config=cfg,
        day_mode=DayMode.SUN_PROTECTION,
        sun_in_funnel=True,
        bright_enough=True,
        tracked_tilt=70,
        current_tilt=10,
    )
    assert resolve(inp).tilt == 45  # configured static tilt


def test_slat_tracking_without_tracked_value_keeps_static_tilt() -> None:
    inp = ResolverInput(
        config=make_cover_config(),
        day_mode=DayMode.SUN_PROTECTION,
        sun_in_funnel=True,
        bright_enough=True,
        tracked_tilt=None,  # no sun data
    )
    assert resolve(inp).tilt == 45


def test_slat_tracking_not_applied_to_heat_protection() -> None:
    # Heat protection wants the slats fully closed; tracking must not open them.
    inp = ResolverInput(
        config=make_cover_config(),
        day_mode=DayMode.HEAT_PROTECTION,
        heat_over_max=True,
        tracked_tilt=70,
        current_tilt=0,
    )
    decision = resolve(inp)
    assert decision.reason is DecisionReason.HEAT_PROTECTION
    assert decision.tilt == 0  # configured heat-protection tilt, not the tracked 70


def test_slat_tracking_applied_to_eco() -> None:
    inp = ResolverInput(
        config=make_cover_config(),
        day_mode=DayMode.ECO,
        sun_in_funnel=True,
        bright_enough=True,
        eco_temp_reached=True,
        tracked_tilt=70,
        current_tilt=10,
    )
    assert resolve(inp).tilt == 70


def test_slat_tracking_dropped_when_tilt_unsupported() -> None:
    cfg = make_cover_config(capabilities=CoverCapabilities(can_position=True, can_tilt=False))
    inp = ResolverInput(
        config=cfg,
        day_mode=DayMode.SUN_PROTECTION,
        sun_in_funnel=True,
        bright_enough=True,
        tracked_tilt=70,
        current_tilt=10,
    )
    assert resolve(inp).tilt is None


# ---------------------------------------------------------------------------
# Diagnostic trace (resolve_trace)
# ---------------------------------------------------------------------------


def _applied(trace, name: str) -> bool:
    return any(c.name == name and c.applied for c in trace.constraints)


def test_resolve_trace_decision_matches_resolve() -> None:
    scenarios = (
        ResolverInput(config=make_cover_config(), fire_active=True, current_position=0),
        ResolverInput(config=make_cover_config(), storm_active=True),
        ResolverInput(
            config=make_cover_config(),
            day_mode=DayMode.SUN_PROTECTION,
            sun_in_funnel=True,
            bright_enough=True,
        ),
        ResolverInput(config=make_cover_config(), current_position=42),
    )
    for inp in scenarios:
        final, trace = resolve_trace(inp)
        assert final == resolve(inp)
        assert trace.final_reason is final.reason


def test_trace_records_selected_driver() -> None:
    _, fire = resolve_trace(
        ResolverInput(config=make_cover_config(), fire_active=True, current_position=0)
    )
    assert fire.selected_driver == "fire"

    _, storm = resolve_trace(ResolverInput(config=make_cover_config(), storm_active=True))
    assert storm.selected_driver == "storm"

    _, sun = resolve_trace(
        ResolverInput(
            config=make_cover_config(),
            day_mode=DayMode.SUN_PROTECTION,
            sun_in_funnel=True,
            bright_enough=True,
        )
    )
    assert sun.selected_driver == "sun_protection"
    # Exactly one rung is marked selected, and it matches.
    selected = [d for d in sun.drivers if d.selected]
    assert len(selected) == 1 and selected[0].matched


def test_trace_records_applied_constraints() -> None:
    _, frost = resolve_trace(
        ResolverInput(config=make_cover_config(), frost_active=True, current_position=0)
    )
    assert _applied(frost, "frost")

    _, lock_open = resolve_trace(
        ResolverInput(config=make_cover_config(), contact_state=ContactState.OPEN)
    )
    assert _applied(lock_open, "lockout_open")

    cfg = make_cover_config()
    _, vent = resolve_trace(
        ResolverInput(
            config=cfg,
            contact_state=ContactState.TILTED,
            day_mode=DayMode.HEAT_PROTECTION,
            heat_over_max=True,
        )
    )
    assert _applied(vent, "lockout_ventilation")

    _, interval = resolve_trace(
        ResolverInput(
            config=make_cover_config(min_movement_interval=300),
            day_mode=DayMode.SUN_PROTECTION,
            sun_in_funnel=True,
            bright_enough=True,
            seconds_since_last_move=1,
            current_position=0,
        )
    )
    assert _applied(interval, "min_interval")


def test_trace_fire_bypasses_constraints() -> None:
    final, trace = resolve_trace(
        ResolverInput(
            config=make_cover_config(min_movement_interval=300),
            fire_active=True,
            frost_active=True,
            seconds_since_last_move=1,
            current_position=0,
        )
    )
    assert final.reason is DecisionReason.FIRE
    assert trace.fire_bypassed_constraints is True
    assert not any(c.applied for c in trace.constraints)
