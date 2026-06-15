"""Select entity for the per-room day mode."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity

from .const import DOMAIN
from .engine import DayMode
from .entity import ShutterEngineRoomEntity

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
    """Set up the room mode selects."""

    coordinator: ShutterEngineCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(RoomModeSelect(coordinator, room.name) for room in coordinator.rooms)


class RoomModeSelect(ShutterEngineRoomEntity, SelectEntity):
    """Exposes ``select.<room>_modus``."""

    _attr_translation_key = "mode"
    _attr_options = [mode.value for mode in DayMode]

    def __init__(self, coordinator: ShutterEngineCoordinator, room_name: str) -> None:
        super().__init__(coordinator, room_name)
        self._attr_unique_id = f"{self._unique_prefix}_mode"

    @property
    def current_option(self) -> str:
        return self.coordinator.room_controls(self._room_name).day_mode.value

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_room_control(self._room_name, day_mode=DayMode(option))
