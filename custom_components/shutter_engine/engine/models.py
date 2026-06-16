"""Configuration data model with layered inheritance.

The configuration is layered ``Hub -> Ruleset -> Controller -> Window``. Every
tunable value may be set on any level; the *deepest* set value wins. A
``Ruleset`` is a reusable behaviour bundle (positions, thresholds, time
windows); a ``Controller`` is bound to a Home Assistant area and references
exactly one ruleset; a ``Window`` is a single controllable cover that picks a
controller and adds its sun funnel, escape-route flag and per-window overrides.

This module implements that resolution and the per-cover defaults seeded by the
shade type.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .const import DayMode, ShadeType


@dataclass(frozen=True)
class ModePosition:
    """Target position (and optional tilt) for a given day mode."""

    position: int
    tilt: int | None = None


@dataclass(frozen=True)
class ProtectionFlags:
    """Per-cover participation in global hazard sources.

    The hazard *source* (the wind/frost sensor) is global; only participation
    is per cover. This is what lets a venetian blind drive to the safe position
    in a storm while a roller shutter next to it keeps shading.
    """

    wind: bool = False
    frost: bool = False


@dataclass(frozen=True)
class CoverCapabilities:
    """Hardware capabilities, auto-detected from the actor where possible."""

    can_position: bool = True
    can_tilt: bool = False


#: Presets seeded by the shade type. Each can be overridden per cover.
SHADE_TYPE_PRESETS: dict[ShadeType, tuple[ProtectionFlags, CoverCapabilities]] = {
    ShadeType.VENETIAN: (
        ProtectionFlags(wind=True, frost=True),
        CoverCapabilities(can_position=True, can_tilt=True),
    ),
    ShadeType.ROLLER_SHUTTER: (
        ProtectionFlags(wind=False, frost=False),
        CoverCapabilities(can_position=True, can_tilt=False),
    ),
    ShadeType.STANDARD: (
        ProtectionFlags(wind=False, frost=False),
        CoverCapabilities(can_position=True, can_tilt=False),
    ),
    ShadeType.CUSTOM: (
        ProtectionFlags(),
        CoverCapabilities(),
    ),
}

#: Default dynamic slat-tracking participation seeded by the shade type. Only
#: venetian blinds re-angle their slats; everything else holds the configured
#: static tilt. Overridable per cover.
SHADE_TYPE_SLAT_TRACKING: dict[ShadeType, bool] = {
    ShadeType.VENETIAN: True,
    ShadeType.ROLLER_SHUTTER: False,
    ShadeType.STANDARD: False,
    ShadeType.CUSTOM: False,
}


def presets_for(shade_type: ShadeType) -> tuple[ProtectionFlags, CoverCapabilities]:
    """Return the (protection, capabilities) presets for ``shade_type``."""

    return SHADE_TYPE_PRESETS.get(shade_type, SHADE_TYPE_PRESETS[ShadeType.CUSTOM])


def slat_tracking_default(shade_type: ShadeType) -> bool:
    """Return the default slat-tracking participation for ``shade_type``."""

    return SHADE_TYPE_SLAT_TRACKING.get(shade_type, False)


# Names of inheritable scalar defaults. ``None`` on a level means "not set
# here, look one level up".
_INHERITABLE_FIELDS: tuple[str, ...] = (
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


@dataclass
class _InheritableDefaults:
    """Mixin holding the inheritable scalar defaults shared by every level."""

    safe_position: int | None = None
    ventilation_position: int | None = None
    brightness_close: float | None = None
    brightness_open: float | None = None
    temp_hysteresis: float | None = None
    azimuth_center: float | None = None
    azimuth_width: float | None = None
    elevation_min: float | None = None
    elevation_max: float | None = None
    delay_close: float | None = None
    delay_open: float | None = None
    min_movement_interval: float | None = None
    sun_tracking_deadband: float | None = None


@dataclass
class HubConfig(_InheritableDefaults):
    """Global defaults and integration-wide entities."""

    sun_entity: str | None = None
    weather_entity: str | None = None
    workday_entity: str | None = None
    wind_entity: str | None = None
    frost_entity: str | None = None
    fire_entity: str | None = None
    burglary_entity: str | None = None


@dataclass
class TimeFunction:
    """Night/morning time-window function configuration.

    Holds one window ``[window_start, window_end]`` plus an optional relative
    offset to the sun event and a random window. ``random_max`` shifts the
    computed trigger by a random ``0..random_max`` minutes whenever it is set.
    """

    enabled: bool = False
    window_start: str | None = None  # "HH:MM"
    window_end: str | None = None  # "HH:MM"
    rel_offset: float | None = None  # minutes relative to sunrise/sunset
    random_max: float = 0.0  # extra random minutes, applied whenever > 0


@dataclass
class ScheduleConfig:
    """A reusable schedule ("Zeitplan") bundling the night and morning windows.

    A schedule groups both time-window functions so it can be selected by a
    ruleset as a whole. A ruleset may pick a weekday schedule and, optionally, a
    separate weekend schedule that is loaded on non-workdays.
    """

    name: str = ""
    night: TimeFunction = field(default_factory=TimeFunction)
    morning: TimeFunction = field(default_factory=TimeFunction)


@dataclass
class RulesetConfig(_InheritableDefaults):
    """A reusable behaviour bundle, selectable by controllers.

    Holds the shade positions per day mode, the inheritable scalar thresholds
    (brightness/temperature/timing) and the schedule references. Many rulesets
    may exist; each controller references exactly one. ``schedule_id`` points to
    a schedule subentry; ``weekend_schedule_id`` is loaded on non-workdays when
    ``weekend_coupling`` is set.
    """

    name: str = ""
    mode_positions: dict[DayMode, ModePosition] = field(default_factory=dict)
    schedule_id: str = ""
    weekend_schedule_id: str = ""
    weekend_coupling: bool = False
    #: Legacy fallback: schedule synthesized from inline night/morning data
    #: stored before schedules became their own subentry. ``None`` for new
    #: rulesets that reference a schedule by id.
    legacy_schedule: ScheduleConfig | None = None


@dataclass
class ControllerConfig(_InheritableDefaults):
    """A controller bound to a Home Assistant area.

    Identified by the Home Assistant ``area_id`` it is bound to. ``name`` is
    only a cached display label resolved from the area registry. References
    exactly one ruleset by its subentry id (``ruleset_id``); an empty or
    dangling reference falls back to the hub defaults.
    """

    area_id: str = ""
    name: str = ""
    day_mode: DayMode = DayMode.OFF
    enabled: bool = True
    locked: bool = False
    holiday: bool = False
    heating_entity: str | None = None
    target_temp: float | None = None  # eco set point
    room_temp_entity: str | None = None
    max_temp: float | None = None  # heat-protection threshold
    ruleset_id: str = ""


@dataclass
class WindowConfig(_InheritableDefaults):
    """A single controllable window surface (one or more cover actors).

    Picks a controller (``controller_id``) and the cover entities it drives. A
    surface may group several covers (e.g. a whole window front in a room); they
    share this configuration but are each resolved individually. ``entity_id``
    holds a single cover for the per-cover resolution path; ``entity_ids`` holds
    the full surface list. Also carries the sun funnel (azimuth/elevation), the
    escape-route flag and any per-window overrides.
    """

    entity_id: str = ""
    entity_ids: list[str] = field(default_factory=list)
    name: str = ""
    controller_id: str = ""
    shade_type: ShadeType = ShadeType.STANDARD
    protection: ProtectionFlags | None = None
    capabilities: CoverCapabilities | None = None
    #: Tri-state dynamic slat tracking: ``None`` falls back to the shade-type
    #: default (on for venetian blinds, off otherwise).
    slat_tracking: bool | None = None
    mode_positions: dict[DayMode, ModePosition] = field(default_factory=dict)
    azimuth_from: float | None = None
    azimuth_to: float | None = None
    brightness_entity: str | None = None
    contact_entity: str | None = None
    is_escape_route: bool = True


@dataclass(frozen=True)
class ResolvedCoverConfig:
    """Fully resolved, flattened configuration for one cover.

    Produced by :func:`resolve_window` after applying inheritance and
    shade-type presets. The resolver consumes only this flat view.
    """

    entity_id: str
    shade_type: ShadeType
    protection: ProtectionFlags
    capabilities: CoverCapabilities
    slat_tracking: bool
    mode_positions: dict[DayMode, ModePosition]
    is_escape_route: bool

    safe_position: int
    ventilation_position: int
    brightness_close: float
    brightness_open: float
    temp_hysteresis: float
    azimuth_center: float | None
    azimuth_width: float | None
    azimuth_from: float | None
    azimuth_to: float | None
    elevation_min: float | None
    elevation_max: float | None
    delay_close: float
    delay_open: float
    min_movement_interval: float
    sun_tracking_deadband: float


#: Hard fallbacks used when a value is set on no level at all.
_HARD_DEFAULTS: dict[str, object] = {
    "safe_position": 0,
    "ventilation_position": 10,
    "brightness_close": 40000.0,
    "brightness_open": 20000.0,
    "temp_hysteresis": 0.5,
    "azimuth_center": None,
    "azimuth_width": None,
    "elevation_min": None,
    "elevation_max": None,
    "delay_close": 0.0,
    "delay_open": 0.0,
    "min_movement_interval": 0.0,
    "sun_tracking_deadband": 5.0,
}


def _inherit(name: str, *levels: _InheritableDefaults) -> object:
    """Return the deepest non-``None`` value for ``name`` across ``levels``.

    ``levels`` must be ordered from deepest (cover) to shallowest (hub).
    """

    for level in levels:
        value = getattr(level, name)
        if value is not None:
            return value
    return _HARD_DEFAULTS[name]


def resolve_window(
    window: WindowConfig,
    controller: ControllerConfig,
    ruleset: RulesetConfig,
    hub: HubConfig,
) -> ResolvedCoverConfig:
    """Flatten the layered config into a single resolved cover view.

    Inheritance is ``Window -> Controller -> Ruleset -> Hub`` (deepest wins).
    Mode positions come from the ruleset, overridden per mode by the window.
    """

    preset_protection, preset_caps = presets_for(window.shade_type)
    protection = window.protection if window.protection is not None else preset_protection
    capabilities = window.capabilities if window.capabilities is not None else preset_caps
    slat_tracking = (
        window.slat_tracking
        if window.slat_tracking is not None
        else slat_tracking_default(window.shade_type)
    )

    chain = (window, controller, ruleset, hub)
    resolved = {name: _inherit(name, *chain) for name in _INHERITABLE_FIELDS}

    # Mode positions: ruleset provides the base, the window overrides per mode.
    mode_positions = dict(ruleset.mode_positions)
    mode_positions.update(window.mode_positions)

    # Azimuth funnel is naturally expressed as a from/to span on the window, but
    # may also be given as center/width on any level. Keep both available.
    return ResolvedCoverConfig(
        entity_id=window.entity_id,
        shade_type=window.shade_type,
        protection=protection,
        capabilities=capabilities,
        slat_tracking=slat_tracking,
        mode_positions=mode_positions,
        is_escape_route=window.is_escape_route,
        azimuth_from=window.azimuth_from,
        azimuth_to=window.azimuth_to,
        **resolved,  # type: ignore[arg-type]
    )
