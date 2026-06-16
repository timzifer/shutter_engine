"""Config, options and subentry flows for the Shutter Engine integration.

The hub (global hazard/sun/weather entities) is configured through the main
config entry and edited through a small options flow. Everything else is split
into individual config *subentries*, each with its own compact add/reconfigure
form and its own device:

* ``schedule``    – a reusable time plan (night/morning windows, offset, random)
* ``ruleset``     – a reusable behaviour bundle (positions, thresholds, schedule)
* ``controller``  – bound to a Home Assistant area; references one ruleset
* ``window``      – a single controllable cover; references a controller
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigSubentryFlow,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.selector import (
    AreaSelector,
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_BURGLARY_ENTITY,
    CONF_FIRE_ENTITY,
    CONF_FROST_ENTITY,
    CONF_IRRADIANCE_ENTITY,
    CONF_SUN_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_WIND_ENTITY,
    CONF_WORKDAY_ENTITY,
    DOMAIN,
    SUBENTRY_CONTROLLER,
    SUBENTRY_RULESET,
    SUBENTRY_SCHEDULE,
    SUBENTRY_WINDOW,
)
from .engine import DayMode, ShadeType

if TYPE_CHECKING:
    from homeassistant.config_entries import SubentryFlowResult
    from homeassistant.data_entry_flow import FlowResult

_DAY_MODES: tuple[str, ...] = tuple(mode.value for mode in DayMode)
_SHADE_TYPES: tuple[str, ...] = tuple(shade.value for shade in ShadeType)
#: Day modes that carry a configurable shade position/tilt.
_SHADE_MODES: tuple[DayMode, ...] = (
    DayMode.SUN_PROTECTION,
    DayMode.ECO,
    DayMode.HEAT_PROTECTION,
)
#: Tri-state slat-tracking choices mapped to ``None``/``True``/``False``.
_TRACKING_DEFAULT = "default"
_TRACKING_ON = "on"
_TRACKING_OFF = "off"


# ---------------------------------------------------------------------------
# Schema field helpers
# ---------------------------------------------------------------------------


def _number(
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    step: float | None = None,
) -> NumberSelector:
    config: dict[str, Any] = {"mode": NumberSelectorMode.BOX}
    if minimum is not None:
        config["min"] = minimum
    if maximum is not None:
        config["max"] = maximum
    if step is not None:
        config["step"] = step
    return NumberSelector(NumberSelectorConfig(**config))


def _select(options: tuple[str, ...]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[SelectOptionDict(value=value, label=value) for value in options],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _ref_select(options: list[SelectOptionDict]) -> SelectSelector:
    """Single-select dropdown listing existing subentries by id/title."""

    return SelectSelector(SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN))


def _dict(pair: tuple[Any, Any]) -> dict[Any, Any]:
    """Turn a ``(key, selector)`` pair into a one-entry schema fragment."""

    return {pair[0]: pair[1]}


def _opt(key: str, defaults: dict[str, Any], selector: Any) -> tuple[Any, Any]:
    """Return an optional field pre-filled with the stored value."""

    return (
        vol.Optional(key, description={"suggested_value": defaults.get(key)}),
        selector,
    )


def _opt2(form_key: str, store: dict[str, Any], store_key: str, selector: Any) -> tuple[Any, Any]:
    """Optional field whose form key differs from the stored key."""

    return (
        vol.Optional(form_key, description={"suggested_value": store.get(store_key)}),
        selector,
    )


def _position(value: Any) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _is_valid_hhmm(value: Any) -> bool:
    """Return whether ``value`` is a valid ``HH:MM`` 24h time string."""

    if value in (None, ""):
        return True  # empty = unset, validated as absent
    try:
        hour, minute = (int(part) for part in str(value).split(":"))
    except (ValueError, AttributeError):
        return False
    return 0 <= hour < 24 and 0 <= minute < 60


def _hub_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the hub configuration schema with optional entity selectors."""

    fields: dict[Any, Any] = {}
    for key, domain in (
        (CONF_SUN_ENTITY, "sun"),
        (CONF_WEATHER_ENTITY, "weather"),
        (CONF_WORKDAY_ENTITY, "binary_sensor"),
        (CONF_WIND_ENTITY, "binary_sensor"),
        (CONF_FROST_ENTITY, "binary_sensor"),
        (CONF_FIRE_ENTITY, "binary_sensor"),
        (CONF_BURGLARY_ENTITY, "binary_sensor"),
        (CONF_IRRADIANCE_ENTITY, "sensor"),
    ):
        key_, sel = _opt(key, defaults, EntitySelector(EntitySelectorConfig(domain=domain)))
        fields[key_] = sel
    return vol.Schema(fields)


def _time_fields(defaults: dict[str, Any]) -> dict[Any, Any]:
    """Night/morning time-window form fragment for a schedule."""

    night = defaults.get("night", {})
    morning = defaults.get("morning", {})
    return {
        vol.Required(
            "night_enabled", description={"suggested_value": night.get("enabled", False)}
        ): BooleanSelector(),
        **_dict(_opt2("night_start", night, "window_start", TextSelector())),
        **_dict(_opt2("night_end", night, "window_end", TextSelector())),
        **_dict(
            _opt2("night_offset", night, "rel_offset", _number(minimum=-120, maximum=120, step=1))
        ),
        **_dict(
            _opt2("night_random", night, "random_max", _number(minimum=0, maximum=120, step=1))
        ),
        vol.Required(
            "morning_enabled", description={"suggested_value": morning.get("enabled", False)}
        ): BooleanSelector(),
        **_dict(_opt2("morning_start", morning, "window_start", TextSelector())),
        **_dict(_opt2("morning_end", morning, "window_end", TextSelector())),
        **_dict(
            _opt2(
                "morning_offset", morning, "rel_offset", _number(minimum=-120, maximum=120, step=1)
            )
        ),
        **_dict(
            _opt2("morning_random", morning, "random_max", _number(minimum=0, maximum=120, step=1))
        ),
    }


def _mode_position_fields(defaults: dict[str, Any]) -> dict[Any, Any]:
    """Per-day-mode position/tilt form fragment."""

    fields: dict[Any, Any] = {}
    modes = defaults.get("mode_positions", {})
    for mode in _SHADE_MODES:
        existing = modes.get(mode.value, {})
        fields.update(
            _dict(
                _opt2(
                    f"{mode.value}_position",
                    existing,
                    "position",
                    _number(minimum=0, maximum=100, step=1),
                )
            )
        )
        fields.update(
            _dict(
                _opt2(
                    f"{mode.value}_tilt", existing, "tilt", _number(minimum=0, maximum=100, step=1)
                )
            )
        )
    return fields


# ---------------------------------------------------------------------------
# Form <-> dict helpers
# ---------------------------------------------------------------------------


def _set_or_drop(target: dict[str, Any], key: str, value: Any) -> None:
    if value in (None, ""):
        target.pop(key, None)
    else:
        target[key] = value


def _update_optional(
    target: dict[str, Any],
    user_input: dict[str, Any],
    *,
    entity_keys: tuple[str, ...] = (),
    float_keys: tuple[str, ...] = (),
    int_keys: tuple[str, ...] = (),
) -> None:
    """Copy present values, dropping cleared ones so inheritance can resume."""

    for key in entity_keys:
        _set_or_drop(target, key, user_input.get(key))
    for key in float_keys:
        value = user_input.get(key)
        _set_or_drop(target, key, float(value) if value not in (None, "") else None)
    for key in int_keys:
        value = user_input.get(key)
        _set_or_drop(target, key, _position(value) if value not in (None, "") else None)


def _time_function(user_input: dict[str, Any], prefix: str) -> dict[str, Any]:
    result: dict[str, Any] = {"enabled": bool(user_input.get(f"{prefix}_enabled", False))}
    start = user_input.get(f"{prefix}_start")
    end = user_input.get(f"{prefix}_end")
    offset = user_input.get(f"{prefix}_offset")
    random_max = user_input.get(f"{prefix}_random")
    if start:
        result["window_start"] = start
    if end:
        result["window_end"] = end
    if offset not in (None, ""):
        result["rel_offset"] = float(offset)
    if random_max not in (None, ""):
        result["random_max"] = float(random_max)
    return result


def _collect_mode_positions(user_input: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for mode in _SHADE_MODES:
        position = _position(user_input.get(f"{mode.value}_position"))
        if position is None:
            continue
        entry: dict[str, Any] = {"position": position}
        tilt = _position(user_input.get(f"{mode.value}_tilt"))
        if tilt is not None:
            entry["tilt"] = tilt
        result[mode.value] = entry
    return result


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    """Drop empty/None values so they fall back through inheritance."""

    return {key: value for key, value in data.items() if value not in (None, "")}


def _area_name(hass: Any, area_id: str | None) -> str | None:
    if not area_id:
        return None
    area = ar.async_get(hass).async_get_area(area_id)
    return area.name if area is not None else None


# ---------------------------------------------------------------------------
# Subentry data builders
# ---------------------------------------------------------------------------


def _schedule_data(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": user_input.get("name") or "Zeitplan",
        "night": _time_function(user_input, "night"),
        "morning": _time_function(user_input, "morning"),
    }


def _schedule_time_errors(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate the HH:MM window fields of a schedule form."""

    for key in ("night_start", "night_end", "morning_start", "morning_end"):
        if not _is_valid_hhmm(user_input.get(key)):
            return {"base": "invalid_time"}
    return {}


def _ruleset_data(user_input: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {"name": user_input.get("name") or "Ruleset"}
    positions = _collect_mode_positions(user_input)
    if positions:
        data["mode_positions"] = positions
    _update_optional(
        data,
        user_input,
        entity_keys=("schedule_id", "weekend_schedule_id"),
        float_keys=(
            "brightness_threshold",
            "brightness_hysteresis",
            "irradiance_threshold",
            "irradiance_hysteresis",
            "temp_hysteresis",
            "sun_tracking_deadband",
            "min_movement_interval",
            "elevation_min",
            "elevation_max",
        ),
        int_keys=("safe_position", "ventilation_position"),
    )
    data["weekend_coupling"] = bool(user_input.get("weekend_coupling", False))
    return data


def _controller_data(user_input: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {
        "area_id": user_input["area_id"],
        "ruleset_id": user_input["ruleset_id"],
        "day_mode": user_input.get("day_mode", DayMode.OFF.value),
    }
    _update_optional(
        data,
        user_input,
        entity_keys=("heating_entity", "room_temp_entity"),
        float_keys=("target_temp", "max_temp"),
    )
    return data


def _window_title(data: dict[str, Any]) -> str:
    """Human-readable subentry title for a (possibly multi-cover) surface.

    Prefers the user-given name; falls back to the cover list, then a generic
    placeholder.
    """

    name = (data.get("name") or "").strip()
    if name:
        return name
    entity_ids = data.get("entity_ids") or []
    return ", ".join(entity_ids) if entity_ids else "Fensterfläche"


def _window_entity_ids(defaults: dict[str, Any]) -> list[str]:
    """Return the surface's cover list, tolerating the legacy single key."""

    if defaults.get("entity_ids"):
        return list(defaults["entity_ids"])
    single = defaults.get("entity_id")
    return [single] if single else []


def _window_data(user_input: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {
        "entity_ids": list(user_input["entity_ids"]),
        "controller_id": user_input["controller_id"],
        "shade_type": user_input.get("shade_type", ShadeType.STANDARD.value),
        "is_escape_route": bool(user_input.get("is_escape_route", True)),
    }
    _set_or_drop(data, "name", user_input.get("name"))
    tracking = user_input.get("slat_tracking", _TRACKING_DEFAULT)
    if tracking != _TRACKING_DEFAULT:
        data["slat_tracking"] = tracking == _TRACKING_ON
    _update_optional(
        data,
        user_input,
        entity_keys=("brightness_entity", "irradiance_entity", "contact_entity"),
        float_keys=(
            "azimuth_from",
            "azimuth_to",
            "elevation_min",
            "elevation_max",
            "sun_tracking_deadband",
            "min_movement_interval",
        ),
        int_keys=("safe_position", "ventilation_position"),
    )
    positions = _collect_mode_positions(user_input)
    if positions:
        data["mode_positions"] = positions
    return data


# ---------------------------------------------------------------------------
# Subentry schemas
# ---------------------------------------------------------------------------


def _schedule_schema(defaults: dict[str, Any]) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required("name", description={"suggested_value": defaults.get("name")}): TextSelector(),
    }
    fields.update(_time_fields(defaults))
    return vol.Schema(fields)


def _ruleset_schema(
    defaults: dict[str, Any], schedule_options: list[SelectOptionDict]
) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required("name", description={"suggested_value": defaults.get("name")}): TextSelector(),
    }
    fields.update(_mode_position_fields(defaults))
    for key, selector in (
        ("brightness_threshold", _number(minimum=0, step=1000)),
        ("brightness_hysteresis", _number(minimum=0, step=1000)),
        ("irradiance_threshold", _number(minimum=0, maximum=1500, step=10)),
        ("irradiance_hysteresis", _number(minimum=0, maximum=500, step=10)),
        ("temp_hysteresis", _number(minimum=0, maximum=10, step=0.1)),
        ("safe_position", _number(minimum=0, maximum=100, step=1)),
        ("ventilation_position", _number(minimum=0, maximum=100, step=1)),
        ("sun_tracking_deadband", _number(minimum=0, maximum=45, step=1)),
        ("min_movement_interval", _number(minimum=0, maximum=3600, step=10)),
        ("elevation_min", _number(minimum=0, maximum=90, step=1)),
        ("elevation_max", _number(minimum=0, maximum=90, step=1)),
    ):
        fields.update(_dict(_opt(key, defaults, selector)))
    fields.update(_dict(_opt("schedule_id", defaults, _ref_select(schedule_options))))
    fields.update(_dict(_opt("weekend_schedule_id", defaults, _ref_select(schedule_options))))
    fields[
        vol.Required(
            "weekend_coupling",
            description={"suggested_value": defaults.get("weekend_coupling", False)},
        )
    ] = BooleanSelector()
    return vol.Schema(fields)


def _controller_schema(
    defaults: dict[str, Any], ruleset_options: list[SelectOptionDict]
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                "area_id", description={"suggested_value": defaults.get("area_id")}
            ): AreaSelector(),
            vol.Required(
                "ruleset_id", description={"suggested_value": defaults.get("ruleset_id")}
            ): _ref_select(ruleset_options),
            **_dict(_opt("day_mode", defaults, _select(_DAY_MODES))),
            **_dict(
                _opt(
                    "heating_entity",
                    defaults,
                    EntitySelector(EntitySelectorConfig(domain="climate")),
                )
            ),
            **_dict(_opt("target_temp", defaults, _number(minimum=5, maximum=30, step=0.5))),
            **_dict(
                _opt(
                    "room_temp_entity",
                    defaults,
                    EntitySelector(EntitySelectorConfig(domain="sensor")),
                )
            ),
            **_dict(_opt("max_temp", defaults, _number(minimum=10, maximum=40, step=0.5))),
        }
    )


def _window_schema(
    defaults: dict[str, Any], controller_options: list[SelectOptionDict]
) -> vol.Schema:
    if "slat_tracking" in defaults:
        tracking = _TRACKING_ON if defaults["slat_tracking"] else _TRACKING_OFF
    else:
        tracking = _TRACKING_DEFAULT
    fields: dict[Any, Any] = {
        **_dict(_opt("name", defaults, TextSelector())),
        vol.Required(
            "entity_ids", description={"suggested_value": _window_entity_ids(defaults)}
        ): EntitySelector(EntitySelectorConfig(domain="cover", multiple=True)),
        vol.Required(
            "controller_id", description={"suggested_value": defaults.get("controller_id")}
        ): _ref_select(controller_options),
        vol.Required(
            "shade_type",
            description={"suggested_value": defaults.get("shade_type", ShadeType.STANDARD.value)},
        ): _select(_SHADE_TYPES),
        vol.Required("slat_tracking", description={"suggested_value": tracking}): _select(
            (_TRACKING_DEFAULT, _TRACKING_ON, _TRACKING_OFF)
        ),
        **_dict(_opt("azimuth_from", defaults, _number(minimum=0, maximum=360, step=1))),
        **_dict(_opt("azimuth_to", defaults, _number(minimum=0, maximum=360, step=1))),
        **_dict(_opt("elevation_min", defaults, _number(minimum=0, maximum=90, step=1))),
        **_dict(_opt("elevation_max", defaults, _number(minimum=0, maximum=90, step=1))),
        **_dict(
            _opt(
                "brightness_entity",
                defaults,
                EntitySelector(EntitySelectorConfig(domain="sensor")),
            )
        ),
        **_dict(
            _opt(
                "irradiance_entity",
                defaults,
                EntitySelector(EntitySelectorConfig(domain="sensor")),
            )
        ),
        **_dict(
            _opt(
                "contact_entity",
                defaults,
                EntitySelector(EntitySelectorConfig(domain="binary_sensor")),
            )
        ),
        vol.Required(
            "is_escape_route",
            description={"suggested_value": defaults.get("is_escape_route", True)},
        ): BooleanSelector(),
        **_dict(_opt("safe_position", defaults, _number(minimum=0, maximum=100, step=1))),
        **_dict(_opt("ventilation_position", defaults, _number(minimum=0, maximum=100, step=1))),
        **_dict(_opt("sun_tracking_deadband", defaults, _number(minimum=0, maximum=45, step=1))),
        **_dict(_opt("min_movement_interval", defaults, _number(minimum=0, maximum=3600, step=10))),
    }
    fields.update(_mode_position_fields(defaults))
    return vol.Schema(fields)


# ---------------------------------------------------------------------------
# Config flow + options flow
# ---------------------------------------------------------------------------


class ShutterEngineConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial hub setup."""

    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        # Single instance: the hub aggregates the global entities. The rooms,
        # controllers and windows are added later as subentries.
        await self.async_set_unique_id(DOMAIN, raise_on_progress=False)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(
                title="Shutter Engine",
                data={"hub": _clean(user_input)},
            )
        return self.async_show_form(step_id="user", data_schema=_hub_schema({}))

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {
            SUBENTRY_SCHEDULE: ScheduleSubentryFlow,
            SUBENTRY_RULESET: RulesetSubentryFlow,
            SUBENTRY_CONTROLLER: ControllerSubentryFlow,
            SUBENTRY_WINDOW: WindowSubentryFlow,
        }

    @staticmethod
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return ShutterEngineOptionsFlow(entry)


class ShutterEngineOptionsFlow(OptionsFlow):
    """Edit the global hub entities."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        current = {**self._entry.data, **self._entry.options}
        if user_input is not None:
            return self.async_create_entry(title="", data={"hub": _clean(user_input)})
        return self.async_show_form(step_id="init", data_schema=_hub_schema(current.get("hub", {})))


# ---------------------------------------------------------------------------
# Subentry flows
# ---------------------------------------------------------------------------


class ScheduleSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure a reusable schedule ("Zeitplan")."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            errors = _schedule_time_errors(user_input)
            data = _schedule_data(user_input)
            if not errors:
                return self.async_create_entry(title=data["name"], data=data)
            return self.async_show_form(
                step_id="user", data_schema=_schedule_schema(data), errors=errors
            )
        return self.async_show_form(step_id="user", data_schema=_schedule_schema({}))

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            errors = _schedule_time_errors(user_input)
            data = _schedule_data(user_input)
            if not errors:
                return self.async_update_and_abort(
                    self._get_entry(), subentry, title=data["name"], data=data
                )
            return self.async_show_form(
                step_id="reconfigure", data_schema=_schedule_schema(data), errors=errors
            )
        return self.async_show_form(
            step_id="reconfigure", data_schema=_schedule_schema(subentry.data)
        )


class RulesetSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure a reusable ruleset."""

    def _schedule_options(self) -> list[SelectOptionDict]:
        entry = self._get_entry()
        return [
            SelectOptionDict(value=sid, label=sub.title)
            for sid, sub in entry.subentries.items()
            if sub.subentry_type == SUBENTRY_SCHEDULE
        ]

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        options = self._schedule_options()
        if user_input is not None:
            data = _ruleset_data(user_input)
            return self.async_create_entry(title=data["name"], data=data)
        return self.async_show_form(step_id="user", data_schema=_ruleset_schema({}, options))

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        options = self._schedule_options()
        if user_input is not None:
            data = _ruleset_data(user_input)
            return self.async_update_and_abort(
                self._get_entry(), subentry, title=data["name"], data=data
            )
        return self.async_show_form(
            step_id="reconfigure", data_schema=_ruleset_schema(subentry.data, options)
        )


class ControllerSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure a controller (one per Home Assistant area)."""

    def _ruleset_options(self) -> list[SelectOptionDict]:
        entry = self._get_entry()
        return [
            SelectOptionDict(value=sid, label=sub.title)
            for sid, sub in entry.subentries.items()
            if sub.subentry_type == SUBENTRY_RULESET
        ]

    def _area_in_use(self, area_id: str, *, exclude: str | None = None) -> bool:
        entry = self._get_entry()
        return any(
            sub.subentry_type == SUBENTRY_CONTROLLER
            and sid != exclude
            and sub.data.get("area_id") == area_id
            for sid, sub in entry.subentries.items()
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        options = self._ruleset_options()
        if not options:
            return self.async_abort(reason="no_rulesets")
        errors: dict[str, str] = {}
        if user_input is not None:
            if self._area_in_use(user_input["area_id"]):
                errors["base"] = "duplicate_area"
            else:
                data = _controller_data(user_input)
                title = _area_name(self.hass, data["area_id"]) or "Controller"
                return self.async_create_entry(title=title, data=data)
        return self.async_show_form(
            step_id="user", data_schema=_controller_schema({}, options), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        options = self._ruleset_options()
        errors: dict[str, str] = {}
        if user_input is not None:
            if self._area_in_use(user_input["area_id"], exclude=subentry.subentry_id):
                errors["base"] = "duplicate_area"
            else:
                data = _controller_data(user_input)
                title = _area_name(self.hass, data["area_id"]) or subentry.title
                return self.async_update_and_abort(
                    self._get_entry(), subentry, title=title, data=data
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_controller_schema(subentry.data, options),
            errors=errors,
        )


class WindowSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure a single controllable window surface."""

    def _controller_options(self) -> list[SelectOptionDict]:
        entry = self._get_entry()
        return [
            SelectOptionDict(value=sid, label=sub.title)
            for sid, sub in entry.subentries.items()
            if sub.subentry_type == SUBENTRY_CONTROLLER
        ]

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        options = self._controller_options()
        if not options:
            return self.async_abort(reason="no_controllers")
        if user_input is not None:
            data = _window_data(user_input)
            return self.async_create_entry(title=_window_title(data), data=data)
        return self.async_show_form(step_id="user", data_schema=_window_schema({}, options))

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        options = self._controller_options()
        if user_input is not None:
            data = _window_data(user_input)
            return self.async_update_and_abort(
                self._get_entry(), subentry, title=_window_title(data), data=data
            )
        return self.async_show_form(
            step_id="reconfigure", data_schema=_window_schema(subentry.data, options)
        )
