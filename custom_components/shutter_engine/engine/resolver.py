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
from .slat import apply_tilt_deadband


@dataclass(frozen=True)
class Decision:
    """The resolver result for a single cover."""

    position: int
    tilt: int | None
    reason: DecisionReason
    #: ``True`` when a constraint suppressed a wanted movement (held in place).
    blocked: bool = False


@dataclass(frozen=True)
class DriverEval:
    """Diagnostic record for one rung of the driver priority ladder."""

    name: str
    #: ``True`` when this rung's condition is met.
    matched: bool
    #: ``True`` only for the first matching rung (the one that won).
    selected: bool = False


@dataclass(frozen=True)
class ConstraintEval:
    """Diagnostic record for one post-ladder constraint."""

    name: str
    #: ``True`` when the constraint changed or vetoed the driver decision.
    applied: bool
    #: Short human-readable effect (e.g. ``"blocked"``, ``"clamped to 10"``).
    effect: str = ""


@dataclass(frozen=True)
class ResolverTrace:
    """Full diagnostic trace of a single resolve pass.

    Surfaces which individual rule (driver) won and which constraints took
    effect, for the controller diagnostics.
    """

    drivers: tuple[DriverEval, ...]
    constraints: tuple[ConstraintEval, ...]
    selected_driver: str
    final_reason: DecisionReason
    #: ``True`` when fire/smoke bypassed the frost/min-interval constraints.
    fire_bypassed_constraints: bool = False


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
    enabled: bool = True
    locked: bool = False

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
    irradiance_sufficient: bool = False
    eco_temp_reached: bool = False  # room at/above eco set point
    heat_over_max: bool = False  # room above max temperature

    # Dynamic venetian slat tracking ---------------------------------------
    #: Cut-off slat tilt computed from the sun elevation by the caller, or
    #: ``None`` when tracking is unavailable (no sun data / disabled).
    tracked_tilt: int | None = None

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


def _mode_target(
    inp: ResolverInput,
    mode: DayMode,
    reason: DecisionReason,
    *,
    track: bool = False,
) -> Decision:
    """Build a decision from the configured position for ``mode``.

    For venetian blinds with dynamic slat tracking enabled, the statically
    configured tilt is replaced by the sun-tracking tilt (subject to the
    configured dead band) while the shade position is kept. Tracking is only
    requested for modes that block the direct beam while admitting diffuse
    light (sun protection, eco); heat protection keeps its fully-closed tilt.
    """

    mp: ModePosition | None = inp.config.mode_positions.get(mode)
    position = POSITION_CLOSED if mp is None else mp.position
    tilt = None if mp is None else mp.tilt
    if track:
        tilt = _tracked_tilt(inp, fallback=tilt)
    return Decision(position=position, tilt=tilt, reason=reason)


def _tracked_tilt(inp: ResolverInput, *, fallback: int | None) -> int | None:
    """Return the dynamic tracking tilt when applicable, else ``fallback``."""

    cfg = inp.config
    if not (cfg.slat_tracking and cfg.capabilities.can_tilt) or inp.tracked_tilt is None:
        return fallback
    return apply_tilt_deadband(inp.tracked_tilt, inp.current_tilt, cfg.sun_tracking_deadband)


def _open(reason: DecisionReason) -> Decision:
    return Decision(position=POSITION_OPEN, tilt=None, reason=reason)


def _burglary_decision(inp: ResolverInput) -> Decision:
    """Burglary target: explicit position if given, else hold."""

    if inp.burglary_position is not None:
        return Decision(position=inp.burglary_position, tilt=None, reason=DecisionReason.BURGLARY)
    return _hold(inp, DecisionReason.BURGLARY)


def _select_driver_traced(inp: ResolverInput) -> tuple[Decision, list[DriverEval]]:
    """Walk the priority ladder, returning the winner plus a per-rung trace.

    Every rung's condition is a side-effect-free predicate, so they can all be
    evaluated up front for the diagnostic trace; the first matching rung wins.
    """

    cfg = inp.config
    day_driver = _day_mode_driver(inp)
    day_name = day_driver.reason.value if day_driver is not None else "day_mode"

    # (name, matched, decision) ordered by descending priority. The final
    # "hold" rung always matches, so a winner is guaranteed.
    rungs: tuple[tuple[str, bool, Decision], ...] = (
        ("fire", inp.fire_active and cfg.is_escape_route, _open(DecisionReason.FIRE)),
        ("burglary", inp.burglary_active, _burglary_decision(inp)),
        (
            "storm",
            inp.storm_active and cfg.protection.wind,
            Decision(position=cfg.safe_position, tilt=None, reason=DecisionReason.STORM),
        ),
        ("disabled", not inp.enabled, _hold(inp, DecisionReason.DISABLED)),
        ("locked", inp.locked, _hold(inp, DecisionReason.LOCKED)),
        ("morning", inp.morning_due, _open(DecisionReason.MORNING)),
        (
            "night",
            inp.night_due,
            Decision(position=POSITION_CLOSED, tilt=None, reason=DecisionReason.NIGHT),
        ),
        (day_name, day_driver is not None, day_driver or _hold(inp, DecisionReason.HOLD)),
        ("hold", True, _hold(inp, DecisionReason.HOLD)),
    )

    chosen: Decision | None = None
    evals: list[DriverEval] = []
    for name, matched, decision in rungs:
        selected = matched and chosen is None
        evals.append(DriverEval(name=name, matched=matched, selected=selected))
        if selected:
            chosen = decision
    assert chosen is not None  # the "hold" rung always matches
    return chosen, evals


def _select_driver(inp: ResolverInput) -> Decision:
    """Walk the priority ladder and return the first matching driver."""

    return _select_driver_traced(inp)[0]


def _day_mode_driver(inp: ResolverInput) -> Decision | None:
    """Resolve the active day mode into a target, or ``None`` when off."""

    shade_conditions = inp.sun_in_funnel and (inp.bright_enough or inp.irradiance_sufficient)

    if inp.day_mode is DayMode.SUN_PROTECTION:
        if shade_conditions:
            return _mode_target(
                inp, DayMode.SUN_PROTECTION, DecisionReason.SUN_PROTECTION, track=True
            )
        return _open(DecisionReason.SUN_PROTECTION)

    if inp.day_mode is DayMode.ECO:
        # Stay open for passive solar heating until the set point is reached.
        if shade_conditions and inp.eco_temp_reached:
            return _mode_target(inp, DayMode.ECO, DecisionReason.ECO, track=True)
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


def _apply_constraints_traced(
    inp: ResolverInput, driver: Decision
) -> tuple[Decision, list[ConstraintEval], bool]:
    """Apply frost, lock-out and minimum-interval constraints, with a trace.

    Returns ``(decision, constraint_evals, fire_bypassed_constraints)``.
    """

    cfg = inp.config
    evals: list[ConstraintEval] = []

    # Fire breaks frost and minimum-interval constraints.
    if driver.reason is DecisionReason.FIRE:
        return driver, evals, True

    # Frost — block movement entirely (priority over storm).
    if inp.frost_active and cfg.protection.frost:
        evals.append(ConstraintEval("frost", True, "blocked"))
        return _hold(inp, DecisionReason.FROST_BLOCK, blocked=True), evals, False
    evals.append(ConstraintEval("frost", False))

    decision = driver

    # Lock-out protection (window contact).
    if inp.contact_state is ContactState.OPEN:
        # Absolute lock: stay/drive fully open. Safety move, bypasses interval.
        evals.append(ConstraintEval("lockout_open", True, "open"))
        return (
            Decision(position=POSITION_OPEN, tilt=None, reason=DecisionReason.LOCKOUT_OPEN),
            evals,
            False,
        )
    evals.append(ConstraintEval("lockout_open", False))

    if inp.contact_state is ContactState.TILTED and decision.position < cfg.ventilation_position:
        # Clamp "close" commands to the ventilation slot.
        decision = Decision(
            position=cfg.ventilation_position,
            tilt=decision.tilt,
            reason=DecisionReason.LOCKOUT_VENTILATION,
        )
        evals.append(
            ConstraintEval("lockout_ventilation", True, f"clamped to {cfg.ventilation_position}")
        )
    else:
        evals.append(ConstraintEval("lockout_ventilation", False))

    # Minimum movement interval — suppress command spam / relay wear.
    if (
        cfg.min_movement_interval > 0
        and inp.seconds_since_last_move is not None
        and inp.seconds_since_last_move < cfg.min_movement_interval
        and decision.position != inp.current_position
    ):
        evals.append(ConstraintEval("min_interval", True, "blocked"))
        return _hold(inp, DecisionReason.MIN_INTERVAL_BLOCK, blocked=True), evals, False
    evals.append(ConstraintEval("min_interval", False))

    return decision, evals, False


def _apply_constraints(inp: ResolverInput, driver: Decision) -> Decision:
    """Apply frost, lock-out and minimum-interval constraints in order."""

    return _apply_constraints_traced(inp, driver)[0]


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


def resolve_trace(inp: ResolverInput) -> tuple[Decision, ResolverTrace]:
    """Resolve a single cover and return the decision plus a diagnostic trace.

    The trace records every driver-ladder rung and constraint evaluation so the
    controller diagnostics can surface which rule won and which constraints
    took effect.
    """

    driver, driver_evals = _select_driver_traced(inp)
    constrained, constraint_evals, fire_bypass = _apply_constraints_traced(inp, driver)
    final = _apply_capabilities(inp, constrained)
    selected = next((d.name for d in driver_evals if d.selected), "hold")
    trace = ResolverTrace(
        drivers=tuple(driver_evals),
        constraints=tuple(constraint_evals),
        selected_driver=selected,
        final_reason=final.reason,
        fire_bypassed_constraints=fire_bypass,
    )
    return final, trace


def resolve(inp: ResolverInput) -> Decision:
    """Resolve the target state for a single cover.

    Returns a :class:`Decision` with the target position, tilt and the reason
    the resolver picked it.
    """

    return resolve_trace(inp)[0]
