"""Assemble the stored subentry dictionaries into engine dataclasses.

This module is pure Python (no Home Assistant import) so the config schema can
be unit-tested in isolation. The config flow produces the subentry
dictionaries; the coordinator reads ``config_entry.subentries`` and feeds the
per-type dictionaries into :func:`build_engine_state`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .engine import (
    ControllerConfig,
    CoverCapabilities,
    DayMode,
    HubConfig,
    ModePosition,
    ProtectionFlags,
    ResolvedCoverConfig,
    RulesetConfig,
    ScheduleConfig,
    ShadeType,
    TimeFunction,
    WindowConfig,
)
from .engine.models import resolve_window

# Inheritable scalar keys shared by every level.
_INHERITABLE_KEYS = (
    "safe_position",
    "ventilation_position",
    "brightness_close",
    "brightness_open",
    "irradiance_close",
    "irradiance_open",
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
    )


def parse_schedule(data: dict[str, Any]) -> ScheduleConfig:
    """Parse a schedule ("Zeitplan") subentry dictionary."""

    return ScheduleConfig(
        name=data.get("name", ""),
        night=_parse_time_function(data.get("night")),
        morning=_parse_time_function(data.get("morning")),
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
        irradiance_entity=data.get("irradiance_entity"),
        **_inheritable(data),
    )


def parse_ruleset(data: dict[str, Any]) -> RulesetConfig:
    """Parse a ruleset subentry dictionary.

    Time windows live in a referenced schedule (``schedule_id``). Rulesets
    stored before schedules became their own subentry carry inline
    ``night``/``morning`` data; those are synthesized into a ``legacy_schedule``
    so existing configurations keep working.
    """

    legacy_schedule: ScheduleConfig | None = None
    weekend_coupling = bool(data.get("weekend_coupling", False))
    if not data.get("schedule_id") and ("night" in data or "morning" in data):
        legacy_schedule = ScheduleConfig(
            night=_parse_time_function(data.get("night")),
            morning=_parse_time_function(data.get("morning")),
        )
        # The old layout stored the weekend toggle on the morning function.
        morning = data.get("morning") or {}
        weekend_coupling = weekend_coupling or bool(morning.get("weekend_coupling", False))

    return RulesetConfig(
        name=data.get("name", ""),
        mode_positions=_parse_mode_positions(data.get("mode_positions")),
        schedule_id=data.get("schedule_id", ""),
        weekend_schedule_id=data.get("weekend_schedule_id", ""),
        weekend_coupling=weekend_coupling,
        legacy_schedule=legacy_schedule,
        **_inheritable(data),
    )


def parse_controller(data: dict[str, Any]) -> ControllerConfig:
    """Parse a controller subentry dictionary."""

    return ControllerConfig(
        area_id=data.get("area_id", ""),
        name=data.get("name", ""),
        day_mode=DayMode(data.get("day_mode", DayMode.OFF.value)),
        enabled=bool(data.get("enabled", True)),
        locked=bool(data.get("locked", False)),
        holiday=bool(data.get("holiday", False)),
        heating_entity=data.get("heating_entity"),
        target_temp=data.get("target_temp"),
        room_temp_entity=data.get("room_temp_entity"),
        max_temp=data.get("max_temp"),
        ruleset_id=data.get("ruleset_id", ""),
        **_inheritable(data),
    )


def parse_window(data: dict[str, Any]) -> WindowConfig:
    """Parse a window subentry dictionary."""

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
    # A surface may drive several covers (``entity_ids``); fall back to the
    # legacy single ``entity_id`` for subentries stored before multi-cover.
    entity_ids = list(data.get("entity_ids") or [])
    if not entity_ids:
        single = data.get("entity_id")
        if single:
            entity_ids = [single]
    return WindowConfig(
        entity_id=data.get("entity_id", ""),
        entity_ids=entity_ids,
        name=data.get("name", ""),
        controller_id=data.get("controller_id", ""),
        shade_type=ShadeType(data.get("shade_type", ShadeType.STANDARD.value)),
        protection=protection,
        capabilities=capabilities,
        slat_tracking=slat_tracking,
        mode_positions=_parse_mode_positions(data.get("mode_positions")),
        azimuth_from=data.get("azimuth_from"),
        azimuth_to=data.get("azimuth_to"),
        brightness_entity=data.get("brightness_entity"),
        irradiance_entity=data.get("irradiance_entity"),
        contact_entity=data.get("contact_entity"),
        is_escape_route=bool(data.get("is_escape_route", True)),
        **_inheritable(data),
    )


@dataclass
class ControllerNode:
    """A parsed controller together with its resolved schedules.

    ``schedule`` is the weekday schedule; ``weekend_schedule`` (optional) is
    loaded on non-workdays when ``weekend_coupling`` is set.
    """

    config: ControllerConfig
    schedule: ScheduleConfig
    weekend_schedule: ScheduleConfig | None
    weekend_coupling: bool


@dataclass
class WindowCoverMember:
    """One cover actor of a window surface with its resolved config.

    All members of a surface share the same configuration; only ``entity_id``
    (the commanded cover) differs, so each is resolved individually.
    """

    entity_id: str
    config: ResolvedCoverConfig


@dataclass
class WindowNode:
    """A resolved window surface ready for the coordinator.

    ``subentry_id`` keys the per-surface device/entities; ``members`` holds the
    one-or-more cover actors that get commanded.
    """

    subentry_id: str
    controller_id: str
    controller: ControllerConfig
    schedule: ScheduleConfig
    weekend_schedule: ScheduleConfig | None
    weekend_coupling: bool
    brightness_entity: str | None
    irradiance_entity: str | None
    contact_entity: str | None
    members: list[WindowCoverMember]


@dataclass
class EngineState:
    """Fully assembled configuration consumed by the coordinator."""

    hub: HubConfig
    controllers: dict[str, ControllerNode] = field(default_factory=dict)
    windows: list[WindowNode] = field(default_factory=list)


def build_engine_state(
    hub_data: dict[str, Any],
    rulesets: dict[str, dict[str, Any]],
    controllers: dict[str, dict[str, Any]],
    windows: dict[str, dict[str, Any]],
    schedules: dict[str, dict[str, Any]] | None = None,
) -> EngineState:
    """Assemble hub/ruleset/controller/window subentry data into an engine state.

    ``rulesets``/``controllers``/``windows``/``schedules`` map
    ``subentry_id -> stored data``. A controller referencing a missing ruleset
    falls back to hub defaults; a window referencing a missing controller is
    skipped. A ruleset referencing a missing schedule falls back to its legacy
    inline schedule (or an empty one).
    """

    hub = parse_hub(hub_data)
    parsed_rulesets = {sid: parse_ruleset(data) for sid, data in rulesets.items()}
    parsed_controllers = {sid: parse_controller(data) for sid, data in controllers.items()}
    parsed_schedules = {sid: parse_schedule(data) for sid, data in (schedules or {}).items()}

    def ruleset_for(controller: ControllerConfig) -> RulesetConfig:
        return parsed_rulesets.get(controller.ruleset_id, RulesetConfig())

    def weekday_schedule_for(ruleset: RulesetConfig) -> ScheduleConfig:
        if ruleset.schedule_id:
            return parsed_schedules.get(ruleset.schedule_id, ScheduleConfig())
        return ruleset.legacy_schedule or ScheduleConfig()

    def weekend_schedule_for(ruleset: RulesetConfig) -> ScheduleConfig | None:
        if ruleset.weekend_schedule_id:
            return parsed_schedules.get(ruleset.weekend_schedule_id)
        return None

    controller_nodes: dict[str, ControllerNode] = {}
    for cid, controller in parsed_controllers.items():
        ruleset = ruleset_for(controller)
        controller_nodes[cid] = ControllerNode(
            config=controller,
            schedule=weekday_schedule_for(ruleset),
            weekend_schedule=weekend_schedule_for(ruleset),
            weekend_coupling=ruleset.weekend_coupling,
        )

    window_nodes: list[WindowNode] = []
    for sid, data in windows.items():
        window = parse_window(data)
        window_controller = parsed_controllers.get(window.controller_id)
        if window_controller is None:
            continue  # dangling controller reference -> skip this window
        ruleset = ruleset_for(window_controller)
        members: list[WindowCoverMember] = []
        for cover_entity in window.entity_ids:
            per_cover = replace(window, entity_id=cover_entity)
            resolved = resolve_window(per_cover, window_controller, ruleset, hub)
            members.append(WindowCoverMember(entity_id=cover_entity, config=resolved))
        if not members:
            continue  # surface without any covers -> nothing to drive
        window_nodes.append(
            WindowNode(
                subentry_id=sid,
                controller_id=window.controller_id,
                controller=window_controller,
                schedule=weekday_schedule_for(ruleset),
                weekend_schedule=weekend_schedule_for(ruleset),
                weekend_coupling=ruleset.weekend_coupling,
                brightness_entity=window.brightness_entity,
                irradiance_entity=window.irradiance_entity,
                contact_entity=window.contact_entity,
                members=members,
            )
        )

    return EngineState(hub=hub, controllers=controller_nodes, windows=window_nodes)
