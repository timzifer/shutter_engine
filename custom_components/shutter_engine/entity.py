"""Shared base class for Shutter Engine room entities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import ShutterEngineCoordinator


class ShutterEngineRoomEntity(CoordinatorEntity["ShutterEngineCoordinator"]):
    """Base entity bound to a room (a Home Assistant device)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ShutterEngineCoordinator, room_name: str) -> None:
        super().__init__(coordinator)
        self._room_name = room_name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_{room_name}")},
            name=room_name,
            manufacturer="Shutter Engine",
            model="Room",
        )

    @property
    def _unique_prefix(self) -> str:
        return f"{self.coordinator.entry.entry_id}_{self._room_name}"
