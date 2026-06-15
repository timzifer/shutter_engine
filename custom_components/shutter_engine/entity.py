"""Shared base class for Shutter Engine room entities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import ShutterEngineCoordinator


def resolve_room_display(hass: HomeAssistant, area_id: str, fallback: str) -> str:
    """Return the Home Assistant area name for ``area_id``, else ``fallback``.

    The room is keyed by ``area_id``; its human-readable label lives in the
    area registry and is resolved live so a renamed area updates everywhere.
    """

    if area_id:
        area = ar.async_get(hass).async_get_area(area_id)
        if area is not None:
            return area.name
    return fallback


class ShutterEngineRoomEntity(CoordinatorEntity["ShutterEngineCoordinator"]):
    """Base entity bound to a room (a Home Assistant device)."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: ShutterEngineCoordinator, area_id: str, display_name: str
    ) -> None:
        super().__init__(coordinator)
        self._area_id = area_id
        self._display_name = display_name
        # The device is bound to its HA area authoritatively after platform
        # setup (see __init__._bind_room_devices_to_areas), so no soft
        # ``suggested_area`` is set here.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_{area_id}")},
            name=display_name,
            manufacturer="Shutter Engine",
            model="Room",
        )

    @property
    def _unique_prefix(self) -> str:
        return f"{self.coordinator.entry.entry_id}_{self._area_id}"
