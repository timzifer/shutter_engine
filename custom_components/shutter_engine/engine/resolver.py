"""The resolver: the heart of the shutter engine (concept section 7).

The resolver runs **per cover** and turns all inputs into exactly one target
position. It is strictly split into:

* **Drivers** — an ordered priority ladder; the *first match wins* and proposes
  a target.
* **Constraints** — applied *after* the ladder; they modify or veto the result.

The fire/smoke driver is special: it breaks the frost and minimum-movement
constraints (life safety before motor protection).

This module is pure Python: it receives an already-resolved
:class:`ResolverInput` and returns a :class:`Decision`. All Home Assistant
interaction (reading states, computing hysteresis/time windows) happens in the
coordinator and is fed in here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .const import (
    POSITION_CLOSED,
    POSITION_OPEN,
    ContactState,
    DayMode,
    DecisionReason,
)
from .models import ModePosition, ResolvedCoverConfig


@dataclass(frozen=True)
class Decision:
    """The resolver result for a single cover."""

    position: int
    tilt: int | None
    reason: DecisionReason
    #: ``True`` when a constraint suppressed a wanted movement (held in place).
    blocked: bool = False


@dataclass
class ResolverInput:
    """Everything the resolver needs to decide for one cover.

    All hysteresis, time-window and funnel evaluation is done by the caller and
    handed in here as plain booleans so that the resolver stays deterministic.
    """

    config: ResolvedCoverConfig

    # Current physical state ------------------------------------------------
    current_position: int = POSITION_OPEN
    current_tilt: int | None = None

    # Room / mode state -----------------------------------------------------
    day_mode: DayMode = DayMode.OFF
    locked: bool = False
    manual_override: bool = False

    # Hazards ---------------------------------------------------------------
    fire_active: bool = False
    burglary_active: bool = False
    storm_active: bool = False
    frost_active: bool = False
    #: Optional explicit burglary target; ``None`` keeps the current position.
    burglary_position: int | None = None

    # Lock-out protection ---------------------------------------------------
    contact_state: ContactState = ContactState.CLOSED

    # Night / morning (already gated by the time-window helper) -------------
    morning_due: bool = False
    night_due: bool = False

    # Day-mode condition flags (already post-hysteresis) -------------------
    sun_in_funnel: bool = False
    bright_enough: bool = False
    eco_temp_reached: bool = False  # room at/above eco set point
    heat_over_max: bool = False  # room above max temperature

    # Minimum movement interval --------------------------------------------
    #: Seconds since the last commanded movement; ``None`` if never moved.
    seconds_since_last_move: float | None = None


# ---------------------------------------------------------------------------
# Drivers (first match wins)
# ---------------------------------------------------------------------------


def _hold(inp: ResolverInput, reason: DecisionReason, *, blocked: bool = False) -> Decision:
    """Return a decision that keeps the current physical position."""

    return Decision(
        position=inp.current_position,
        tilt=inp.current_tilt,
        reason=reason,
        blocked=blocked,
    )


def _mode_target(inp: ResolverInput, mode: DayMode, reason: DecisionReason) -> Decision:
    """Build a decision from the configured position for ``mode``."""

    mp: ModePosition | None = inp.config.mode_positions.get(mode)
    if mp is None:
        # No explicit shade position configured -> fully close.
        return Decision(position=POSITION_CLOSED, tilt=None, reason=reason)
    return Decision(position=mp.position, tilt=mp.tilt, reason=reason)


def _open(reason: DecisionReason) -> Decision:
    return Decision(position=POSITION_OPEN, tilt=None, reason=reason)


def _select_driver(inp: ResolverInput) -> Decision:
    """Walk the priority ladder and return the first matching driver."""

    cfg = inp.config

    # 1. Fire / smoke (escape route) — unconditional open, breaks constraints.
    if inp.fire_active and cfg.is_escape_route:
        return _open(DecisionReason.FIRE)

    # 2. Burglary / security — default: no action (hold), optional position.
    if inp.burglary_active:
        if inp.burglary_position is not None:
            return Decision(
                position=inp.burglary_position,
                tilt=None,
                reason=DecisionReason.BURGLARY,
            )
        return _hold(inp, DecisionReason.BURGLARY)

    # 3. Storm — safe position, only for covers participating in wind protection.
    if inp.storm_active and cfg.protection.wind:
        return Decision(
            position=cfg.safe_position,
            tilt=None,
            reason=DecisionReason.STORM,
        )

    # 4. Lock / manual override — hold and suspend automation.
    if inp.locked:
        return _hold(inp, DecisionReason.LOCKED)
    if inp.manual_override:
        return _hold(inp, DecisionReason.MANUAL_OVERRIDE)

    # 5. Night / morning — gated by the time-window helper upstream.
    if inp.morning_due:
        return _open(DecisionReason.MORNING)
    if inp.night_due:
        return Decision(position=POSITION_CLOSED, tilt=None, reason=DecisionReason.NIGHT)

    # 6. Sun / eco / heat protection.
    driver = _day_mode_driver(inp)
    if driver is not None:
        return driver

    # 7. Default — hold last position.
    return _hold(inp, DecisionReason.HOLD)


def _day_mode_driver(inp: ResolverInput) -> Decision | None:
    """Resolve the active day mode into a target, or ``None`` when off."""

    shade_conditions = inp.sun_in_funnel and inp.bright_enough

    if inp.day_mode is DayMode.SUN_PROTECTION:
        if shade_conditions:
            return _mode_target(inp, DayMode.SUN_PROTECTION, DecisionReason.SUN_PROTECTION)
        return _open(DecisionReason.SUN_PROTECTION)

    if inp.day_mode is DayMode.ECO:
        # Stay open for passive solar heating until the set point is reached.
        if shade_conditions and inp.eco_temp_reached:
            return _mode_target(inp, DayMode.ECO, DecisionReason.ECO)
        return _open(DecisionReason.ECO)

    if inp.day_mode is DayMode.HEAT_PROTECTION:
        # Close on overheating even without direct sun, or on normal shading.
        if inp.heat_over_max or shade_conditions:
            return _mode_target(inp, DayMode.HEAT_PROTECTION, DecisionReason.HEAT_PROTECTION)
        return _open(DecisionReason.HEAT_PROTECTION)

    # DayMode.OFF -> no driver.
    return None


# ---------------------------------------------------------------------------
# Constraints (applied after the ladder)
# ---------------------------------------------------------------------------


def _apply_constraints(inp: ResolverInput, driver: Decision) -> Decision:
    """Apply frost, lock-out and minimum-interval constraints in order."""

    cfg = inp.config

    # Fire breaks frost and minimum-interval constraints.
    if driver.reason is DecisionReason.FIRE:
        return driver

    # Frost — block movement entirely (priority over storm).
    if inp.frost_active and cfg.protection.frost:
        return _hold(inp, DecisionReason.FROST_BLOCK, blocked=True)

    decision = driver

    # Lock-out protection (window contact).
    if inp.contact_state is ContactState.OPEN:
        # Absolute lock: stay/drive fully open. Safety move, bypasses interval.
        return Decision(
            position=POSITION_OPEN,
            tilt=None,
            reason=DecisionReason.LOCKOUT_OPEN,
        )
    if inp.contact_state is ContactState.TILTED and decision.position < cfg.ventilation_position:
        # Clamp "close" commands to the ventilation slot.
        decision = Decision(
            position=cfg.ventilation_position,
            tilt=decision.tilt,
            reason=DecisionReason.LOCKOUT_VENTILATION,
        )

    # Minimum movement interval — suppress command spam / relay wear.
    if (
        cfg.min_movement_interval > 0
        and inp.seconds_since_last_move is not None
        and inp.seconds_since_last_move < cfg.min_movement_interval
        and decision.position != inp.current_position
    ):
        return _hold(inp, DecisionReason.MIN_INTERVAL_BLOCK, blocked=True)

    return decision


# ---------------------------------------------------------------------------
# Capability mapping
# ---------------------------------------------------------------------------


def _apply_capabilities(inp: ResolverInput, decision: Decision) -> Decision:
    """Down-map a decision to the cover's hardware capabilities."""

    cfg = inp.config
    position = decision.position
    tilt = decision.tilt

    if not cfg.capabilities.can_position:
        # On/Off/Stop only -> binary mapping (Phase 1, see concept section 8).
        position = POSITION_OPEN if position > POSITION_CLOSED else POSITION_CLOSED

    if not cfg.capabilities.can_tilt:
        tilt = None

    if position == decision.position and tilt == decision.tilt:
        return decision
    return Decision(
        position=position,
        tilt=tilt,
        reason=decision.reason,
        blocked=decision.blocked,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def resolve(inp: ResolverInput) -> Decision:
    """Resolve the target state for a single cover.

    Returns a :class:`Decision` with the target position, tilt and the reason
    the resolver picked it.
    """

    driver = _select_driver(inp)
    constrained = _apply_constraints(inp, driver)
    return _apply_capabilities(inp, constrained)
