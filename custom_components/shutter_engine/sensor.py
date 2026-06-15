"""Diagnostic status sensor per room."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorEntity

from .const import DOMAIN
from .entity import ShutterEngineRoomEntity, resolve_room_display

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
    """Set up the per-room status sensors."""

    coordinator: ShutterEngineCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        RoomStatusSensor(
            coordinator,
            room.area_id,
            resolve_room_display(hass, room.area_id, room.name or room.area_id),
        )
        for room in coordinator.rooms
    )


class RoomStatusSensor(ShutterEngineRoomEntity, SensorEntity):
    """Exposes ``sensor.<room>_status`` with a per-cover diagnostic text."""

    _attr_translation_key = "status"
    _attr_icon = "mdi:window-shutter-cog"

    def __init__(
        self, coordinator: ShutterEngineCoordinator, area_id: str, display_name: str
    ) -> None:
        super().__init__(coordinator, area_id, display_name)
        self._attr_unique_id = f"{self._unique_prefix}_status"

    @property
    def native_value(self) -> str:
        results = self.coordinator.cover_results_for_room(self._area_id)
        if not results:
            return "idle"
        # Summarize with the most relevant (first) cover; details in attributes.
        return results[0].status_text

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        results = self.coordinator.cover_results_for_room(self._area_id)
        return {result.decision.reason.value: result.status_text for result in results}
