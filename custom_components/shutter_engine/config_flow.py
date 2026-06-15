"""Config and options flow for the Shutter Engine integration.

The hub (global hazard/sun/weather entities) is configured through guided
selector steps. The room/area/cover tree is edited through a guided,
step-by-step editor (menus to navigate, forms to edit). A raw JSON editor is
kept as an *advanced* escape hatch for bulk edits and import/export.
"""

from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
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

from .config import parse_config
from .const import (
    CONF_BURGLARY_ENTITY,
    CONF_FIRE_ENTITY,
    CONF_FROST_ENTITY,
    CONF_SUN_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_WIND_ENTITY,
    CONF_WORKDAY_ENTITY,
    DOMAIN,
)
from .engine import DayMode, ShadeType

if TYPE_CHECKING:
    from homeassistant.data_entry_flow import FlowResult

# Sentinel selection values for the navigation lists.
_ADD = "__add__"
_BACK = "__back__"
_DONE = "__done__"

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


def _hub_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the hub configuration schema with optional entity selectors."""

    def optional(key: str, domain: str | list[str]):
        return vol.Optional(
            key,
            description={"suggested_value": defaults.get(key)},
        ), EntitySelector(EntitySelectorConfig(domain=domain))

    fields: dict[Any, Any] = {}
    for key, domain in (
        (CONF_SUN_ENTITY, "sun"),
        (CONF_WEATHER_ENTITY, "weather"),
        (CONF_WORKDAY_ENTITY, "binary_sensor"),
        (CONF_WIND_ENTITY, "binary_sensor"),
        (CONF_FROST_ENTITY, "binary_sensor"),
        (CONF_FIRE_ENTITY, "binary_sensor"),
        (CONF_BURGLARY_ENTITY, "binary_sensor"),
    ):
        opt_key, selector = optional(key, domain)
        fields[opt_key] = selector
    return vol.Schema(fields)


class ShutterEngineConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        # Single instance: the hub aggregates everything. ``raise_on_progress``
        # is disabled so that a setup attempt the user abandoned (e.g. by
        # closing the dialog) does not leave a lingering in-progress flow that
        # would abort every later attempt with "already_in_progress".
        await self.async_set_unique_id(DOMAIN, raise_on_progress=False)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(
                title="Shutter Engine",
                data={"hub": _clean(user_input), "rooms": []},
            )

        return self.async_show_form(step_id="user", data_schema=_hub_schema({}))

    @staticmethod
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return ShutterEngineOptionsFlow(entry)


# ---------------------------------------------------------------------------
# Schema field helpers (shared by the guided editor)
# ---------------------------------------------------------------------------


def _opt(key: str, defaults: dict[str, Any], selector: Any) -> tuple[Any, Any]:
    """Return an optional field pre-filled with the stored value."""

    return (
        vol.Optional(key, description={"suggested_value": defaults.get(key)}),
        selector,
    )


def _number(
    mode: NumberSelectorMode = NumberSelectorMode.BOX,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    step: float | None = None,
) -> NumberSelector:
    config: dict[str, Any] = {"mode": mode}
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


def _nav_schema(items: list[str], add_label: str, tail_value: str, tail_label: str) -> vol.Schema:
    """Build a navigation select listing ``items`` plus add and a tail action.

    ``tail_value`` is ``_DONE`` at the top level (save & finish) or ``_BACK``
    inside a sub-list (return to the parent menu).
    """

    options = [SelectOptionDict(value=str(i), label=name) for i, name in enumerate(items)]
    options.append(SelectOptionDict(value=_ADD, label=add_label))
    options.append(SelectOptionDict(value=tail_value, label=tail_label))
    return vol.Schema(
        {
            vol.Required("selection"): SelectSelector(
                SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
            )
        }
    )


def _position(value: Any) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


class ShutterEngineOptionsFlow(OptionsFlow):
    """Edit the hub entities and the room tree."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        current = {**entry.data, **entry.options}
        # Working copy mutated by the guided editor; committed on "Save & finish".
        self._rooms: list[dict[str, Any]] = copy.deepcopy(current.get("rooms", []))
        self._room_idx: int | None = None
        self._area_idx: int | None = None
        self._cover_idx: int | None = None

    # -- shared state accessors -------------------------------------------

    def _current(self) -> dict[str, Any]:
        return {**self._entry.data, **self._entry.options}

    def _area_name(self, area_id: str | None) -> str | None:
        """Resolve an ``area_id`` to its current Home Assistant area name."""

        if not area_id:
            return None
        area = ar.async_get(self.hass).async_get_area(area_id)
        return area.name if area is not None else None

    def _area_in_use(self, area_id: str, *, exclude: int | None = None) -> bool:
        """Return whether another room already maps to ``area_id``."""

        return any(
            room.get("area_id") == area_id for idx, room in enumerate(self._rooms) if idx != exclude
        )

    def _room(self) -> dict[str, Any]:
        return self._rooms[self._room_idx]  # type: ignore[index]

    def _areas(self) -> list[dict[str, Any]]:
        return self._room().setdefault("areas", [])

    def _area(self) -> dict[str, Any]:
        return self._areas()[self._area_idx]  # type: ignore[index]

    def _covers(self) -> list[dict[str, Any]]:
        return self._area().setdefault("covers", [])

    def _cover(self) -> dict[str, Any]:
        return self._covers()[self._cover_idx]  # type: ignore[index]

    # -- top level --------------------------------------------------------

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(step_id="init", menu_options=["hub", "rooms", "rooms_json"])

    async def async_step_hub(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        current = self._current()
        if user_input is not None:
            return self._save({**current, "hub": _clean(user_input)})
        return self.async_show_form(step_id="hub", data_schema=_hub_schema(current.get("hub", {})))

    async def async_step_rooms_json(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        current = self._current()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                rooms = json.loads(user_input["rooms_json"])
                if not isinstance(rooms, list):
                    raise ValueError("rooms must be a list")
                _validate_room_areas(rooms)
                parse_config({"hub": current.get("hub", {}), "rooms": rooms})
            except (ValueError, KeyError):
                errors["base"] = "invalid_rooms"
            else:
                self._rooms = rooms
                return self._save({**current, "rooms": rooms})

        suggested = json.dumps(self._rooms, indent=2, ensure_ascii=False)
        schema = vol.Schema(
            {vol.Required("rooms_json", description={"suggested_value": suggested}): str}
        )
        return self.async_show_form(step_id="rooms_json", data_schema=schema, errors=errors)

    # -- room navigation --------------------------------------------------

    async def async_step_rooms(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            choice = user_input["selection"]
            if choice == _ADD:
                return await self.async_step_room_add()
            if choice == _DONE:
                current = self._current()
                try:
                    parse_config({"hub": current.get("hub", {}), "rooms": self._rooms})
                except (ValueError, KeyError):
                    errors["base"] = "invalid_rooms"
                else:
                    return self._save({**current, "rooms": self._rooms})
            else:
                self._room_idx = int(choice)
                return await self.async_step_room_menu()

        names = [
            self._area_name(r.get("area_id"))
            or r.get("name")
            or r.get("area_id")
            or f"Room {i + 1}"
            for i, r in enumerate(self._rooms)
        ]
        schema = _nav_schema(
            names, add_label="Add room", tail_value=_DONE, tail_label="Save & finish"
        )
        return self.async_show_form(step_id="rooms", data_schema=schema, errors=errors)

    async def async_step_room_add(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            area_id = user_input["area_id"]
            if self._area_in_use(area_id):
                errors["base"] = "duplicate_area"
            else:
                self._rooms.append(
                    {"area_id": area_id, "name": self._area_name(area_id) or "", "areas": []}
                )
                self._room_idx = len(self._rooms) - 1
                return await self.async_step_room_menu()
        schema = vol.Schema({vol.Required("area_id"): AreaSelector()})
        return self.async_show_form(step_id="room_add", data_schema=schema, errors=errors)

    async def async_step_room_menu(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(
            step_id="room_menu",
            menu_options=["room_edit", "room_time", "room_areas", "room_delete", "rooms"],
        )

    async def async_step_room_edit(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        room = self._room()
        errors: dict[str, str] = {}
        if user_input is not None:
            area_id = user_input["area_id"]
            if self._area_in_use(area_id, exclude=self._room_idx):
                errors["base"] = "duplicate_area"
            else:
                room["area_id"] = area_id
                room["name"] = self._area_name(area_id) or ""
                _update_optional(
                    room,
                    user_input,
                    entity_keys=("heating_entity", "room_temp_entity"),
                    float_keys=("target_temp", "max_temp"),
                )
                if "day_mode" in user_input:
                    room["day_mode"] = user_input["day_mode"]
                return await self.async_step_room_menu()

        schema = vol.Schema(
            {
                vol.Required(
                    "area_id", description={"suggested_value": room.get("area_id")}
                ): AreaSelector(),
                **_dict(_opt("day_mode", room, _select(_DAY_MODES))),
                **_dict(
                    _opt(
                        "heating_entity",
                        room,
                        EntitySelector(EntitySelectorConfig(domain="climate")),
                    )
                ),
                **_dict(_opt("target_temp", room, _number(minimum=5, maximum=30, step=0.5))),
                **_dict(
                    _opt(
                        "room_temp_entity",
                        room,
                        EntitySelector(EntitySelectorConfig(domain="sensor")),
                    )
                ),
                **_dict(_opt("max_temp", room, _number(minimum=10, maximum=40, step=0.5))),
            }
        )
        return self.async_show_form(step_id="room_edit", data_schema=schema, errors=errors)

    async def async_step_room_time(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        room = self._room()
        night = room.get("night", {})
        morning = room.get("morning", {})
        if user_input is not None:
            room["night"] = _time_function(user_input, "night")
            room["morning"] = _time_function(user_input, "morning", weekend=True)
            return await self.async_step_room_menu()

        schema = vol.Schema(
            {
                vol.Required(
                    "night_enabled", description={"suggested_value": night.get("enabled", False)}
                ): BooleanSelector(),
                **_dict(_opt2("night_start", night, "window_start", TextSelector())),
                **_dict(_opt2("night_end", night, "window_end", TextSelector())),
                **_dict(
                    _opt2(
                        "night_offset",
                        night,
                        "rel_offset",
                        _number(minimum=-120, maximum=120, step=1),
                    )
                ),
                vol.Required(
                    "morning_enabled",
                    description={"suggested_value": morning.get("enabled", False)},
                ): BooleanSelector(),
                **_dict(_opt2("morning_start", morning, "window_start", TextSelector())),
                **_dict(_opt2("morning_end", morning, "window_end", TextSelector())),
                **_dict(
                    _opt2(
                        "morning_offset",
                        morning,
                        "rel_offset",
                        _number(minimum=-120, maximum=120, step=1),
                    )
                ),
                vol.Required(
                    "morning_weekend_coupling",
                    description={"suggested_value": morning.get("weekend_coupling", False)},
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="room_time", data_schema=schema)

    async def async_step_room_delete(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        del self._rooms[self._room_idx]  # type: ignore[index]
        self._room_idx = None
        return await self.async_step_rooms()

    # -- area navigation --------------------------------------------------

    async def async_step_room_areas(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            choice = user_input["selection"]
            if choice == _ADD:
                return await self.async_step_area_add()
            if choice == _BACK:
                return await self.async_step_room_menu()
            self._area_idx = int(choice)
            return await self.async_step_area_menu()

        names = [a.get("name") or f"Area {i + 1}" for i, a in enumerate(self._areas())]
        schema = _nav_schema(names, add_label="Add area", tail_value=_BACK, tail_label="Back")
        return self.async_show_form(step_id="room_areas", data_schema=schema)

    async def async_step_area_add(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._areas().append({"name": user_input["name"], "covers": []})
            self._area_idx = len(self._areas()) - 1
            return await self.async_step_area_menu()
        schema = vol.Schema({vol.Required("name"): TextSelector()})
        return self.async_show_form(step_id="area_add", data_schema=schema)

    async def async_step_area_menu(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(
            step_id="area_menu",
            menu_options=["area_edit", "area_covers", "area_delete", "room_areas"],
        )

    async def async_step_area_edit(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        area = self._area()
        if user_input is not None:
            area["name"] = user_input.get("name", area.get("name", ""))
            area["is_escape_route"] = bool(user_input.get("is_escape_route", True))
            _update_optional(
                area,
                user_input,
                entity_keys=("brightness_entity", "contact_entity"),
                float_keys=("azimuth_from", "azimuth_to", "elevation_min", "elevation_max"),
            )
            return await self.async_step_area_menu()

        schema = vol.Schema(
            {
                vol.Required(
                    "name", description={"suggested_value": area.get("name")}
                ): TextSelector(),
                **_dict(_opt("azimuth_from", area, _number(minimum=0, maximum=360, step=1))),
                **_dict(_opt("azimuth_to", area, _number(minimum=0, maximum=360, step=1))),
                **_dict(_opt("elevation_min", area, _number(minimum=0, maximum=90, step=1))),
                **_dict(_opt("elevation_max", area, _number(minimum=0, maximum=90, step=1))),
                **_dict(
                    _opt(
                        "brightness_entity",
                        area,
                        EntitySelector(EntitySelectorConfig(domain="sensor")),
                    )
                ),
                **_dict(
                    _opt(
                        "contact_entity",
                        area,
                        EntitySelector(EntitySelectorConfig(domain="binary_sensor")),
                    )
                ),
                vol.Required(
                    "is_escape_route",
                    description={"suggested_value": area.get("is_escape_route", True)},
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="area_edit", data_schema=schema)

    async def async_step_area_delete(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        del self._areas()[self._area_idx]  # type: ignore[index]
        self._area_idx = None
        return await self.async_step_room_areas()

    # -- cover navigation -------------------------------------------------

    async def async_step_area_covers(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            choice = user_input["selection"]
            if choice == _ADD:
                return await self.async_step_cover_add()
            if choice == _BACK:
                return await self.async_step_area_menu()
            self._cover_idx = int(choice)
            return await self.async_step_cover_menu()

        names = [c.get("entity_id") or f"Cover {i + 1}" for i, c in enumerate(self._covers())]
        schema = _nav_schema(names, add_label="Add cover", tail_value=_BACK, tail_label="Back")
        return self.async_show_form(step_id="area_covers", data_schema=schema)

    async def async_step_cover_add(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._covers().append(
                {
                    "entity_id": user_input["entity_id"],
                    "shade_type": user_input.get("shade_type", ShadeType.STANDARD.value),
                    "mode_positions": {},
                }
            )
            self._cover_idx = len(self._covers()) - 1
            return await self.async_step_cover_menu()
        schema = vol.Schema(
            {
                vol.Required("entity_id"): EntitySelector(EntitySelectorConfig(domain="cover")),
                vol.Required("shade_type", default=ShadeType.STANDARD.value): _select(_SHADE_TYPES),
            }
        )
        return self.async_show_form(step_id="cover_add", data_schema=schema)

    async def async_step_cover_menu(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(
            step_id="cover_menu",
            menu_options=["cover_edit", "cover_modes", "cover_delete", "area_covers"],
        )

    async def async_step_cover_edit(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        cover = self._cover()
        if user_input is not None:
            cover["entity_id"] = user_input["entity_id"]
            cover["shade_type"] = user_input.get("shade_type", cover.get("shade_type"))
            tracking = user_input.get("slat_tracking", _TRACKING_DEFAULT)
            if tracking == _TRACKING_DEFAULT:
                cover.pop("slat_tracking", None)
            else:
                cover["slat_tracking"] = tracking == _TRACKING_ON
            _update_optional(
                cover,
                user_input,
                float_keys=("sun_tracking_deadband", "min_movement_interval"),
                int_keys=("safe_position", "ventilation_position"),
            )
            return await self.async_step_cover_menu()

        if "slat_tracking" in cover:
            tracking = _TRACKING_ON if cover["slat_tracking"] else _TRACKING_OFF
        else:
            tracking = _TRACKING_DEFAULT
        schema = vol.Schema(
            {
                vol.Required(
                    "entity_id", description={"suggested_value": cover.get("entity_id")}
                ): EntitySelector(EntitySelectorConfig(domain="cover")),
                vol.Required(
                    "shade_type", description={"suggested_value": cover.get("shade_type")}
                ): _select(_SHADE_TYPES),
                vol.Required("slat_tracking", description={"suggested_value": tracking}): _select(
                    (_TRACKING_DEFAULT, _TRACKING_ON, _TRACKING_OFF)
                ),
                **_dict(
                    _opt("sun_tracking_deadband", cover, _number(minimum=0, maximum=45, step=1))
                ),
                **_dict(_opt("safe_position", cover, _number(minimum=0, maximum=100, step=1))),
                **_dict(
                    _opt("ventilation_position", cover, _number(minimum=0, maximum=100, step=1))
                ),
                **_dict(
                    _opt("min_movement_interval", cover, _number(minimum=0, maximum=3600, step=10))
                ),
            }
        )
        return self.async_show_form(step_id="cover_edit", data_schema=schema)

    async def async_step_cover_modes(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        cover = self._cover()
        modes = cover.setdefault("mode_positions", {})
        if user_input is not None:
            new_modes: dict[str, Any] = {}
            for mode in _SHADE_MODES:
                position = _position(user_input.get(f"{mode.value}_position"))
                if position is None:
                    continue
                entry: dict[str, Any] = {"position": position}
                tilt = _position(user_input.get(f"{mode.value}_tilt"))
                if tilt is not None:
                    entry["tilt"] = tilt
                new_modes[mode.value] = entry
            cover["mode_positions"] = new_modes
            return await self.async_step_cover_menu()

        fields: dict[Any, Any] = {}
        for mode in _SHADE_MODES:
            existing = modes.get(mode.value, {})
            pos_key, pos_sel = _opt2(
                f"{mode.value}_position",
                existing,
                "position",
                _number(minimum=0, maximum=100, step=1),
            )
            tilt_key, tilt_sel = _opt2(
                f"{mode.value}_tilt", existing, "tilt", _number(minimum=0, maximum=100, step=1)
            )
            fields[pos_key] = pos_sel
            fields[tilt_key] = tilt_sel
        return self.async_show_form(step_id="cover_modes", data_schema=vol.Schema(fields))

    async def async_step_cover_delete(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        del self._covers()[self._cover_idx]  # type: ignore[index]
        self._cover_idx = None
        return await self.async_step_area_covers()

    # -- persistence ------------------------------------------------------

    def _save(self, new: dict[str, Any]) -> FlowResult:
        return self.async_create_entry(title="", data=_options_only(new))


# ---------------------------------------------------------------------------
# Form <-> dict helpers
# ---------------------------------------------------------------------------


def _dict(pair: tuple[Any, Any]) -> dict[Any, Any]:
    """Turn a ``(key, selector)`` pair into a one-entry schema fragment."""

    return {pair[0]: pair[1]}


def _opt2(form_key: str, store: dict[str, Any], store_key: str, selector: Any) -> tuple[Any, Any]:
    """Optional field whose form key differs from the stored key."""

    return (
        vol.Optional(form_key, description={"suggested_value": store.get(store_key)}),
        selector,
    )


def _validate_room_areas(rooms: list[Any]) -> None:
    """Ensure every room carries a non-empty, unique ``area_id``."""

    seen: set[str] = set()
    for room in rooms:
        area_id = room.get("area_id") if isinstance(room, dict) else None
        if not area_id:
            raise ValueError("each room needs a non-empty area_id")
        if area_id in seen:
            raise ValueError(f"duplicate area_id: {area_id}")
        seen.add(area_id)


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


def _set_or_drop(target: dict[str, Any], key: str, value: Any) -> None:
    if value in (None, ""):
        target.pop(key, None)
    else:
        target[key] = value


def _time_function(
    user_input: dict[str, Any], prefix: str, *, weekend: bool = False
) -> dict[str, Any]:
    result: dict[str, Any] = {"enabled": bool(user_input.get(f"{prefix}_enabled", False))}
    start = user_input.get(f"{prefix}_start")
    end = user_input.get(f"{prefix}_end")
    offset = user_input.get(f"{prefix}_offset")
    if start:
        result["window_start"] = start
    if end:
        result["window_end"] = end
    if offset not in (None, ""):
        result["rel_offset"] = float(offset)
    if weekend:
        result["weekend_coupling"] = bool(user_input.get(f"{prefix}_weekend_coupling", False))
    return result


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    """Drop empty/None values so they fall back through inheritance."""

    return {key: value for key, value in data.items() if value not in (None, "")}


def _options_only(data: dict[str, Any]) -> dict[str, Any]:
    """Keep only the hub/rooms payload for the options entry."""

    return {"hub": data.get("hub", {}), "rooms": data.get("rooms", [])}
