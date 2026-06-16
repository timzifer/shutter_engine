"""Switch entities for per-controller control (enabled, lock, night, morning, holiday)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity

from .const import DOMAIN
from .entity import ShutterEngineControllerEntity, resolve_area_display

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ShutterEngineCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the per-controller control switches."""

    coordinator: ShutterEngineCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = []
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != "controller":
            continue
        display = resolve_area_display(hass, subentry.data.get("area_id", ""), subentry.title)
        batch = [
            ControllerEnabledSwitch(coordinator, subentry_id, display),
            ControllerLockSwitch(coordinator, subentry_id, display),
            ControllerNightSwitch(coordinator, subentry_id, display),
            ControllerMorningSwitch(coordinator, subentry_id, display),
            ControllerHolidaySwitch(coordinator, subentry_id, display),
        ]
        _LOGGER.debug(
            "Creating %d switch entities for controller %s (%s)",
            len(batch),
            subentry_id,
            display,
        )
        async_add_entities(batch, config_subentry_id=subentry_id)


class _ControllerSwitch(ShutterEngineControllerEntity, SwitchEntity):
    """Base for controller control switches."""

    _control_attr: str

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_controller_control(
            self._controller_id, **{self._control_attr: True}
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_controller_control(
            self._controller_id, **{self._control_attr: False}
        )


class ControllerEnabledSwitch(_ControllerSwitch):
    """switch.<controller>_enabled — gates all routine automation."""

    _attr_translation_key = "enabled"
    _attr_icon = "mdi:robot"
    _control_attr = "enabled"

    def __init__(
        self, coordinator: ShutterEngineCoordinator, controller_id: str, display_name: str
    ) -> None:
        super().__init__(coordinator, controller_id, display_name)
        self._attr_unique_id = f"{self._unique_prefix}_enabled"

    @property
    def is_on(self) -> bool:
        return self.coordinator.controller_controls(self._controller_id).enabled


class ControllerLockSwitch(_ControllerSwitch):
    """switch.<controller>_lock — locks covers in current position."""

    _attr_translation_key = "lock"
    _attr_icon = "mdi:lock"
    _control_attr = "locked"

    def __init__(
        self, coordinator: ShutterEngineCoordinator, controller_id: str, display_name: str
    ) -> None:
        super().__init__(coordinator, controller_id, display_name)
        self._attr_unique_id = f"{self._unique_prefix}_lock"

    @property
    def is_on(self) -> bool:
        return self.coordinator.controller_controls(self._controller_id).locked


class ControllerNightSwitch(_ControllerSwitch):
    """switch.<controller>_night — gates the night time window."""

    _attr_translation_key = "night"
    _attr_icon = "mdi:weather-night"
    _control_attr = "night_enabled"

    def __init__(
        self, coordinator: ShutterEngineCoordinator, controller_id: str, display_name: str
    ) -> None:
        super().__init__(coordinator, controller_id, display_name)
        self._attr_unique_id = f"{self._unique_prefix}_night"

    @property
    def is_on(self) -> bool:
        return self.coordinator.controller_controls(self._controller_id).night_enabled


class ControllerMorningSwitch(_ControllerSwitch):
    """switch.<controller>_morning — gates the morning time window."""

    _attr_translation_key = "morning"
    _attr_icon = "mdi:weather-sunset-up"
    _control_attr = "morning_enabled"

    def __init__(
        self, coordinator: ShutterEngineCoordinator, controller_id: str, display_name: str
    ) -> None:
        super().__init__(coordinator, controller_id, display_name)
        self._attr_unique_id = f"{self._unique_prefix}_morning"

    @property
    def is_on(self) -> bool:
        return self.coordinator.controller_controls(self._controller_id).morning_enabled


class ControllerHolidaySwitch(_ControllerSwitch):
    """switch.<controller>_holiday — holiday randomization mode."""

    _attr_translation_key = "holiday"
    _attr_icon = "mdi:bag-suitcase"
    _control_attr = "holiday"

    def __init__(
        self, coordinator: ShutterEngineCoordinator, controller_id: str, display_name: str
    ) -> None:
        super().__init__(coordinator, controller_id, display_name)
        self._attr_unique_id = f"{self._unique_prefix}_holiday"

    @property
    def is_on(self) -> bool:
        return self.coordinator.controller_controls(self._controller_id).holiday
