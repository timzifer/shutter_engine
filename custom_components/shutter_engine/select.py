"""Select entity for the per-controller day mode."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity

from .const import DOMAIN
from .engine import DayMode
from .entity import ShutterEngineControllerEntity, resolve_area_display

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ShutterEngineCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the controller mode selects, one per controller subentry."""

    coordinator: ShutterEngineCoordinator = hass.data[DOMAIN][entry.entry_id]
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != "controller":
            continue
        display = resolve_area_display(hass, subentry.data.get("area_id", ""), subentry.title)
        async_add_entities(
            [RoomModeSelect(coordinator, subentry_id, display)],
            config_subentry_id=subentry_id,
        )


class RoomModeSelect(ShutterEngineControllerEntity, SelectEntity):
    """Exposes ``select.<controller>_mode``."""

    _attr_translation_key = "mode"
    _attr_options = [mode.value for mode in DayMode]

    def __init__(
        self, coordinator: ShutterEngineCoordinator, controller_id: str, display_name: str
    ) -> None:
        super().__init__(coordinator, controller_id, display_name)
        self._attr_unique_id = f"{self._unique_prefix}_mode"

    @property
    def current_option(self) -> str:
        return self.coordinator.controller_controls(self._controller_id).day_mode.value

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_controller_control(
            self._controller_id, day_mode=DayMode(option)
        )
