"""Shared base classes for Shutter Engine subentry entities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import ShutterEngineCoordinator


def resolve_area_display(hass: HomeAssistant, area_id: str, fallback: str) -> str:
    """Return the Home Assistant area name for ``area_id``, else ``fallback``.

    A controller is keyed by ``area_id``; its human-readable label lives in the
    area registry and is resolved live so a renamed area updates everywhere.
    """

    if area_id:
        area = ar.async_get(hass).async_get_area(area_id)
        if area is not None:
            return area.name
    return fallback


class ShutterEngineControllerEntity(CoordinatorEntity["ShutterEngineCoordinator"]):
    """Base entity bound to a controller (a Home Assistant device)."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: ShutterEngineCoordinator, controller_id: str, display_name: str
    ) -> None:
        super().__init__(coordinator)
        self._controller_id = controller_id
        self._display_name = display_name
        # The device is bound to its HA area authoritatively after platform
        # setup (see __init__._bind_controller_devices_to_areas).
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"controller_{controller_id}")},
            name=display_name,
            manufacturer="Shutter Engine",
            model="Controller",
        )

    @property
    def _unique_prefix(self) -> str:
        return f"controller_{self._controller_id}"


class ShutterEngineWindowEntity(CoordinatorEntity["ShutterEngineCoordinator"]):
    """Base entity bound to a single window cover (a Home Assistant device)."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: ShutterEngineCoordinator, subentry_id: str, display_name: str
    ) -> None:
        super().__init__(coordinator)
        self._subentry_id = subentry_id
        self._display_name = display_name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"window_{subentry_id}")},
            name=display_name,
            manufacturer="Shutter Engine",
            model="Window",
        )

    @property
    def _unique_prefix(self) -> str:
        return f"window_{self._subentry_id}"
