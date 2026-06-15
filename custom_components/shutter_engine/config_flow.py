"""Config and options flow for the Shutter Engine integration.

The hub (global hazard/sun/weather entities) is configured through guided
selector steps. The room/area/cover tree is large and nested; it is edited as a
validated JSON document in the options flow. A fully guided, step-by-step tree
editor is a planned enhancement (see the README roadmap).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
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

if TYPE_CHECKING:
    from homeassistant.data_entry_flow import FlowResult


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

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        # Single instance: the hub aggregates everything.
        await self.async_set_unique_id(DOMAIN)
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


class ShutterEngineOptionsFlow(OptionsFlow):
    """Edit the hub entities and the room tree."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry

    def _current(self) -> dict[str, Any]:
        return {**self._entry.data, **self._entry.options}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(step_id="init", menu_options=["hub", "rooms"])

    async def async_step_hub(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        current = self._current()
        if user_input is not None:
            new = {**current, "hub": _clean(user_input)}
            return self.async_create_entry(title="", data=_options_only(new))
        return self.async_show_form(step_id="hub", data_schema=_hub_schema(current.get("hub", {})))

    async def async_step_rooms(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        current = self._current()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                rooms = json.loads(user_input["rooms_json"])
                if not isinstance(rooms, list):
                    raise ValueError("rooms must be a list")
                # Validate by attempting a full parse.
                parse_config({"hub": current.get("hub", {}), "rooms": rooms})
            except (ValueError, KeyError) as err:
                errors["base"] = "invalid_rooms"
                _ = err
            else:
                new = {**current, "rooms": rooms}
                return self.async_create_entry(title="", data=_options_only(new))

        suggested = json.dumps(current.get("rooms", []), indent=2, ensure_ascii=False)
        schema = vol.Schema(
            {
                vol.Required(
                    "rooms_json",
                    description={"suggested_value": suggested},
                ): str
            }
        )
        return self.async_show_form(step_id="rooms", data_schema=schema, errors=errors)


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    """Drop empty/None values so they fall back through inheritance."""

    return {key: value for key, value in data.items() if value not in (None, "")}


def _options_only(data: dict[str, Any]) -> dict[str, Any]:
    """Keep only the hub/rooms payload for the options entry."""

    return {"hub": data.get("hub", {}), "rooms": data.get("rooms", [])}
