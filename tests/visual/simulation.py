"""A minimal, Home-Assistant-free re-implementation of the coordinator loop.

The resolver itself only consumes pre-computed booleans (``sun_in_funnel``,
``bright_enough``, ``heat_over_max`` …). To make a *time-series* simulation
realistic rather than hand-wave the flags, this harness mirrors exactly what
:class:`ShutterEngineCoordinator` does each update cycle: it takes the **raw**
sensor-level inputs (sun elevation/azimuth, indoor temperature, event flags)
and derives the resolver booleans with the very same engine helpers the
coordinator uses (:func:`in_sun_funnel`, :func:`estimate_brightness`, the
hysteresis helpers and :func:`slat_tilt_for_elevation`).

The wiring deliberately follows ``coordinator.py``:

* brightness goes through a *stateful* :class:`TemperatureHysteresis` created
  once per run (``coordinator.py`` stores it on ``CoverRuntime``);
* eco/heat temperature checks build a *fresh* hysteresis each step, exactly like
  ``_eco_temp_reached`` / ``_heat_over_max``;
* the dynamic slat tilt is computed like ``_tracked_tilt``;
* after each decision, :func:`plan_command` decides which axes actually move and
  the physical position/tilt and the momentary ``last_target`` baseline are
  advanced just like ``_apply_decision``.

The result is a list of :class:`Frame` objects — one per simulated minute —
that the plotting module turns into a chart.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from custom_components.shutter_engine.engine import (
    ENFORCED_DRIVER_REASONS,
    MOMENTARY_DRIVER_REASONS,
    ContactState,
    DayMode,
    ResolvedCoverConfig,
    ResolverInput,
    SlatMode,
    TemperatureHysteresis,
    estimate_brightness,
    in_sun_funnel,
    plan_command,
    resolve_trace,
    slat_tilt_for_elevation,
    slat_tilt_physical,
)
from custom_components.shutter_engine.engine.const import POSITION_OPEN
from tests.conftest import make_cover_config

#: Reasons that advance the momentary ``last_target`` baseline (mirrors the
#: coordinator's ``_ACTIONABLE_REASONS``: every enforced or momentary driver).
ACTIONABLE_REASONS = ENFORCED_DRIVER_REASONS | MOMENTARY_DRIVER_REASONS

MINUTES_PER_DAY = 24 * 60


@dataclass
class RawInput:
    """Raw, sensor-level inputs for a single simulated minute."""

    minute: int
    elevation: float
    azimuth: float
    #: Temperature of the heating/comfort sensor, compared against the eco set
    #: point (``target_temp``) to derive ``eco_temp_reached``.
    heating_temp: float
    #: Room temperature compared against ``max_temp`` to derive ``heat_over_max``.
    room_temp: float
    cloud_coverage: float = 0.0
    locked: bool = False
    enabled: bool = True
    fire_active: bool = False
    burglary_active: bool = False
    storm_active: bool = False
    frost_active: bool = False
    contact_state: ContactState = ContactState.CLOSED


@dataclass
class Frame:
    """One resolved time step: raw inputs, derived flags and resolver output."""

    minute: int
    # Raw inputs --------------------------------------------------------------
    elevation: float
    azimuth: float
    brightness: float
    heating_temp: float
    room_temp: float
    locked: bool
    fire_active: bool
    burglary_active: bool
    storm_active: bool
    frost_active: bool
    contact_state: ContactState
    # Derived booleans (post-funnel / post-hysteresis) ------------------------
    sun_in_funnel: bool
    bright_enough: bool
    eco_temp_reached: bool
    heat_over_max: bool
    tracked_tilt: int | None
    # Resolver output ---------------------------------------------------------
    #: Physical cover position after the (possibly momentary) command.
    position: int
    #: Physical slat tilt after the command, if the cover can tilt.
    tilt: int | None
    #: Target position the resolver decided this step (may differ from the
    #: physical position when a momentary driver chose not to re-issue a move).
    target: int
    reason: str
    blocked: bool
    moved: bool


@dataclass
class ControllerParams:
    """Controller-level knobs the coordinator would read from config."""

    day_mode: DayMode = DayMode.OFF
    enabled: bool = True
    #: Eco set point (``ControllerConfig.target_temp``); ``None`` disables eco
    #: gating, matching the coordinator's "behave like plain sun protection".
    target_temp: float | None = None
    #: Heat-protection ceiling (``ControllerConfig.max_temp``).
    max_temp: float | None = None
    #: Optional explicit burglary target position.
    burglary_position: int | None = None


@dataclass
class Scenario:
    """A named time-series case ready to be simulated and plotted."""

    name: str
    title: str
    description: str
    controller: ControllerParams
    inputs: list[RawInput]
    config_overrides: dict = field(default_factory=dict)
    #: Initial physical cover position before the first step (blind up by default).
    start_position: int = POSITION_OPEN


# ---------------------------------------------------------------------------
# Default synthetic day (sun arc + a plausible indoor temperature curve)
# ---------------------------------------------------------------------------


def sun_elevation(minute: int, *, peak: float = 55.0) -> float:
    """A smooth elevation arc: below the horizon at night, peak around noon.

    Models a half-sine between sunrise (~06:00) and sunset (~20:00). Values
    below the horizon are returned negative so funnel/brightness behave like the
    real helpers (which clamp at zero).
    """

    sunrise, sunset = 6 * 60, 20 * 60
    if minute <= sunrise or minute >= sunset:
        return -5.0
    from math import pi, sin

    fraction = (minute - sunrise) / (sunset - sunrise)
    return peak * sin(pi * fraction)


def sun_azimuth(minute: int) -> float:
    """Azimuth sweeping from east (~90°) at sunrise to west (~270°) at sunset."""

    sunrise, sunset = 6 * 60, 20 * 60
    if minute <= sunrise:
        return 90.0
    if minute >= sunset:
        return 270.0
    fraction = (minute - sunrise) / (sunset - sunrise)
    return 90.0 + 180.0 * fraction


def indoor_temperature(minute: int, *, base: float = 19.0, swing: float = 6.0) -> float:
    """A lagging indoor temperature curve that peaks in the afternoon.

    Coarse model: warms through the day and peaks ~2 h after solar noon, so the
    room keeps heating after the sun has started to drop — which is exactly when
    eco / heat-protection become interesting.
    """

    from math import pi, sin

    # Peak near 15:00 (900 min); coldest near 03:00.
    fraction = (minute - 180) / MINUTES_PER_DAY
    return base + swing * max(0.0, sin(pi * fraction))


def default_day(
    minute: int,
    *,
    base_temp: float = 19.0,
    temp_swing: float = 6.0,
    cloud_coverage: float = 0.0,
) -> RawInput:
    """Build the baseline :class:`RawInput` for ``minute`` of the synthetic day."""

    temp = indoor_temperature(minute, base=base_temp, swing=temp_swing)
    return RawInput(
        minute=minute,
        elevation=sun_elevation(minute),
        azimuth=sun_azimuth(minute),
        heating_temp=temp,
        room_temp=temp,
        cloud_coverage=cloud_coverage,
    )


def build_day(
    overrides: Callable[[RawInput], RawInput] | None = None,
    **day_kwargs,
) -> list[RawInput]:
    """Return a full day of :class:`RawInput` at one-minute resolution.

    ``overrides`` may post-process each minute to inject events (lock windows,
    fire, burglary, clouds …).
    """

    day = [default_day(minute, **day_kwargs) for minute in range(MINUTES_PER_DAY)]
    if overrides is not None:
        day = [overrides(raw) for raw in day]
    return day


# ---------------------------------------------------------------------------
# Derivation of the resolver booleans (mirrors the coordinator)
# ---------------------------------------------------------------------------


def _tracked_tilt(cfg: ResolvedCoverConfig, elevation: float) -> int | None:
    """Mirror of ``ShutterEngineCoordinator._tracked_tilt``."""

    if not (cfg.slat_tracking and cfg.capabilities.can_tilt):
        return None
    if cfg.slat_mode == SlatMode.PHYSICAL and cfg.slat_depth_mm and cfg.slat_distance_mm:
        return slat_tilt_physical(
            elevation,
            slat_depth_mm=cfg.slat_depth_mm,
            slat_distance_mm=cfg.slat_distance_mm,
        )
    elevation_low = cfg.elevation_min if cfg.elevation_min is not None else 0.0
    elevation_high = cfg.elevation_max if cfg.elevation_max is not None else 90.0
    return slat_tilt_for_elevation(
        elevation,
        elevation_low=elevation_low,
        elevation_high=elevation_high,
    )


def run_scenario(scenario: Scenario) -> list[Frame]:
    """Simulate ``scenario`` minute by minute and return the resulting frames."""

    cfg = make_cover_config(**scenario.config_overrides)
    controller = scenario.controller

    # Stateful brightness hysteresis, created once like the coordinator stores it
    # on ``CoverRuntime`` (note: it uses ``TemperatureHysteresis`` for brightness).
    brightness_hyst = TemperatureHysteresis(
        set_point=cfg.brightness_threshold,
        hysteresis=cfg.brightness_hysteresis,
    )

    current_position = scenario.start_position
    current_tilt: int | None = None
    last_target: int | None = None
    last_tilt: int | None = None
    last_move_minute: int | None = None

    frames: list[Frame] = []
    for raw in scenario.inputs:
        brightness = estimate_brightness(raw.elevation, raw.cloud_coverage)
        bright_enough = brightness_hyst.update(brightness)
        sun_in_funnel = in_sun_funnel(
            raw.azimuth,
            raw.elevation,
            cfg.azimuth_from,
            cfg.azimuth_to,
            cfg.elevation_min,
            cfg.elevation_max,
        )

        # Eco: fresh hysteresis each step, like ``_eco_temp_reached``. With no
        # set point the coordinator behaves like plain sun protection (True).
        if controller.target_temp is None:
            eco_temp_reached = True
        else:
            eco_temp_reached = TemperatureHysteresis(
                controller.target_temp, cfg.temp_hysteresis
            ).update(raw.heating_temp)

        # Heat: fresh hysteresis each step, like ``_heat_over_max``.
        if controller.max_temp is None:
            heat_over_max = False
        else:
            heat_over_max = TemperatureHysteresis(controller.max_temp, cfg.temp_hysteresis).update(
                raw.room_temp
            )

        tracked_tilt = _tracked_tilt(cfg, raw.elevation)
        seconds_since_last_move = (
            None if last_move_minute is None else (raw.minute - last_move_minute) * 60.0
        )

        inp = ResolverInput(
            config=cfg,
            current_position=current_position,
            current_tilt=current_tilt,
            day_mode=controller.day_mode,
            enabled=controller.enabled and raw.enabled,
            locked=raw.locked,
            fire_active=raw.fire_active,
            burglary_active=raw.burglary_active,
            storm_active=raw.storm_active,
            frost_active=raw.frost_active,
            burglary_position=controller.burglary_position,
            contact_state=raw.contact_state,
            sun_in_funnel=sun_in_funnel,
            bright_enough=bright_enough,
            eco_temp_reached=eco_temp_reached,
            heat_over_max=heat_over_max,
            tracked_tilt=tracked_tilt,
            seconds_since_last_move=seconds_since_last_move,
        )

        decision, _trace = resolve_trace(inp)
        plan = plan_command(
            decision,
            current_position=current_position,
            current_tilt=current_tilt,
            last_target=last_target,
            last_tilt=last_tilt,
            can_tilt=cfg.capabilities.can_tilt,
        )

        # Advance the physical state exactly like ``_apply_decision`` would once
        # Home Assistant has executed the service calls.
        if plan.position is not None:
            current_position = plan.position
        if plan.tilt is not None:
            current_tilt = plan.tilt
        if plan.moves:
            last_move_minute = raw.minute
        if not decision.blocked and decision.reason in ACTIONABLE_REASONS:
            last_target = decision.position
            last_tilt = decision.tilt

        frames.append(
            Frame(
                minute=raw.minute,
                elevation=raw.elevation,
                azimuth=raw.azimuth,
                brightness=brightness,
                heating_temp=raw.heating_temp,
                room_temp=raw.room_temp,
                locked=raw.locked,
                fire_active=raw.fire_active,
                burglary_active=raw.burglary_active,
                storm_active=raw.storm_active,
                frost_active=raw.frost_active,
                contact_state=raw.contact_state,
                sun_in_funnel=sun_in_funnel,
                bright_enough=bright_enough,
                eco_temp_reached=eco_temp_reached,
                heat_over_max=heat_over_max,
                tracked_tilt=tracked_tilt,
                position=current_position,
                tilt=current_tilt,
                target=decision.position,
                reason=decision.reason.value,
                blocked=decision.blocked,
                moved=plan.moves,
            )
        )

    return frames
