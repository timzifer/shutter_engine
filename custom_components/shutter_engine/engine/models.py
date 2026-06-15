"""Configuration data model with four-level inheritance.

The configuration is layered ``Hub -> Room -> Area -> Cover``. Every tunable
value may be set on any level; the *deepest* set value wins. This module
implements that resolution and the per-cover defaults seeded by the shade type.
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


def presets_for(shade_type: ShadeType) -> tuple[ProtectionFlags, CoverCapabilities]:
    """Return the (protection, capabilities) presets for ``shade_type``."""

    return SHADE_TYPE_PRESETS.get(shade_type, SHADE_TYPE_PRESETS[ShadeType.CUSTOM])


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
    """Night/morning time-window function configuration."""

    enabled: bool = False
    window_start: str | None = None  # "HH:MM"
    window_end: str | None = None  # "HH:MM"
    rel_offset: float | None = None  # minutes relative to sunrise/sunset
    random_max: float = 0.0  # extra random minutes, active with holiday switch
    weekend_coupling: bool = False  # morning only: load weekend window on non-workdays


@dataclass
class RoomConfig(_InheritableDefaults):
    """A room, exposed as a Home Assistant device."""

    name: str = ""
    day_mode: DayMode = DayMode.OFF
    locked: bool = False
    holiday: bool = False
    heating_entity: str | None = None
    target_temp: float | None = None  # eco set point
    room_temp_entity: str | None = None
    max_temp: float | None = None  # heat-protection threshold
    night: TimeFunction = field(default_factory=TimeFunction)
    morning: TimeFunction = field(default_factory=TimeFunction)
    areas: list[AreaConfig] = field(default_factory=list)


@dataclass
class AreaConfig(_InheritableDefaults):
    """A window area inside a room (horizontal/vertical sun funnel)."""

    name: str = ""
    azimuth_from: float | None = None
    azimuth_to: float | None = None
    brightness_entity: str | None = None
    contact_entity: str | None = None
    is_escape_route: bool = True
    covers: list[CoverConfig] = field(default_factory=list)


@dataclass
class CoverConfig(_InheritableDefaults):
    """A single cover (the actual actor)."""

    entity_id: str = ""
    shade_type: ShadeType = ShadeType.STANDARD
    protection: ProtectionFlags | None = None
    capabilities: CoverCapabilities | None = None
    mode_positions: dict[DayMode, ModePosition] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedCoverConfig:
    """Fully resolved, flattened configuration for one cover.

    Produced by :func:`resolve_cover_config` after applying inheritance and
    shade-type presets. The resolver consumes only this flat view.
    """

    entity_id: str
    shade_type: ShadeType
    protection: ProtectionFlags
    capabilities: CoverCapabilities
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


def resolve_cover_config(
    cover: CoverConfig,
    area: AreaConfig,
    room: RoomConfig,
    hub: HubConfig,
) -> ResolvedCoverConfig:
    """Flatten the four-level config into a single resolved cover view."""

    preset_protection, preset_caps = presets_for(cover.shade_type)
    protection = cover.protection if cover.protection is not None else preset_protection
    capabilities = cover.capabilities if cover.capabilities is not None else preset_caps

    chain = (cover, area, room, hub)
    resolved = {name: _inherit(name, *chain) for name in _INHERITABLE_FIELDS}

    # Azimuth funnel is naturally expressed as a from/to span on the area, but
    # may also be given as center/width on any level. Keep both available.
    return ResolvedCoverConfig(
        entity_id=cover.entity_id,
        shade_type=cover.shade_type,
        protection=protection,
        capabilities=capabilities,
        mode_positions=dict(cover.mode_positions),
        is_escape_route=area.is_escape_route,
        azimuth_from=area.azimuth_from,
        azimuth_to=area.azimuth_to,
        **resolved,  # type: ignore[arg-type]
    )
