"""Binary sensor entities for controller automation state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .const import DOMAIN
from .engine.const import DecisionReason
from .entity import ShutterEngineControllerEntity, resolve_area_display

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ShutterEngineCoordinator

_INACTIVE_REASONS = frozenset({
    DecisionReason.DISABLED,
    DecisionReason.LOCKED,
    DecisionReason.MANUAL_OVERRIDE,
    DecisionReason.HOLD,
})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors for each controller."""

    coordinator: ShutterEngineCoordinator = hass.data[DOMAIN][entry.entry_id]
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != "controller":
            continue
        display = resolve_area_display(hass, subentry.data.get("area_id", ""), subentry.title)
        async_add_entities(
            [
                ControllerActiveBinarySensor(coordinator, subentry_id, display),
                ControllerBlockedBinarySensor(coordinator, subentry_id, display),
            ],
            config_subentry_id=subentry_id,
        )


class ControllerActiveBinarySensor(ShutterEngineControllerEntity, BinarySensorEntity):
    """Whether the controller is actively automating covers.

    ON when enabled, not locked, and not overridden by manual intervention.
    Useful as a condition in automations or as a visible indicator.
    """

    _attr_translation_key = "active"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:robot"

    def __init__(
        self, coordinator: ShutterEngineCoordinator, controller_id: str, display_name: str
    ) -> None:
        super().__init__(coordinator, controller_id, display_name)
        self._attr_unique_id = f"{self._unique_prefix}_active"

    @property
    def is_on(self) -> bool:
        controls = self.coordinator.controller_controls(self._controller_id)
        if not controls.enabled or controls.locked:
            return False
        members = [
            member
            for result in self.coordinator.cover_results_for_controller(self._controller_id)
            for member in result.members
        ]
        return bool(members) and all(
            member.decision.reason not in _INACTIVE_REASONS for member in members
        )


class ControllerBlockedBinarySensor(ShutterEngineControllerEntity, BinarySensorEntity):
    """Whether any cover in this controller is blocked by a constraint."""

    _attr_translation_key = "blocked"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:hand-back-left-off"
    _attr_entity_category = None

    def __init__(
        self, coordinator: ShutterEngineCoordinator, controller_id: str, display_name: str
    ) -> None:
        super().__init__(coordinator, controller_id, display_name)
        self._attr_unique_id = f"{self._unique_prefix}_blocked"

    @property
    def is_on(self) -> bool:
        return any(
            member.decision.blocked
            for result in self.coordinator.cover_results_for_controller(self._controller_id)
            for member in result.members
        )

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        attrs: dict[str, str] = {}
        for result in self.coordinator.cover_results_for_controller(self._controller_id):
            for member in result.members:
                if member.decision.blocked:
                    applied = [c.name for c in member.trace.constraints if c.applied]
                    attrs[member.entity_id] = ", ".join(applied) if applied else "blocked"
        return attrs
