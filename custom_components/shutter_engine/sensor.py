"""Diagnostic status sensors per controller and per window."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .entity import (
    ShutterEngineControllerEntity,
    ShutterEngineWindowEntity,
    resolve_area_display,
)

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
    """Set up the per-controller status/debug sensors and per-window sensors."""

    coordinator: ShutterEngineCoordinator = hass.data[DOMAIN][entry.entry_id]
    managed_windows = set(coordinator.window_ids())

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type == "controller":
            display = resolve_area_display(hass, subentry.data.get("area_id", ""), subentry.title)
            async_add_entities(
                [
                    ControllerStatusSensor(coordinator, subentry_id, display),
                    ControllerDebugSensor(coordinator, subentry_id, display),
                ],
                config_subentry_id=subentry_id,
            )
        elif subentry.subentry_type == "window" and subentry_id in managed_windows:
            async_add_entities(
                [WindowStatusSensor(coordinator, subentry_id, subentry.title)],
                config_subentry_id=subentry_id,
            )


class ControllerStatusSensor(ShutterEngineControllerEntity, SensorEntity):
    """Exposes ``sensor.<controller>_status`` with a per-cover diagnostic text."""

    _attr_translation_key = "status"
    _attr_icon = "mdi:window-shutter-cog"

    def __init__(
        self, coordinator: ShutterEngineCoordinator, controller_id: str, display_name: str
    ) -> None:
        super().__init__(coordinator, controller_id, display_name)
        self._attr_unique_id = f"{self._unique_prefix}_status"

    @property
    def native_value(self) -> str:
        results = self.coordinator.cover_results_for_controller(self._controller_id)
        if not results:
            return "idle"
        # Summarize with the most relevant (first) cover; details in attributes.
        return results[0].status_text

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        results = self.coordinator.cover_results_for_controller(self._controller_id)
        return {result.decision.reason.value: result.status_text for result in results}


class ControllerDebugSensor(ShutterEngineControllerEntity, SensorEntity):
    """Diagnostic sensor exposing the resolved decision per cover."""

    _attr_translation_key = "debug"
    _attr_icon = "mdi:bug-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: ShutterEngineCoordinator, controller_id: str, display_name: str
    ) -> None:
        super().__init__(coordinator, controller_id, display_name)
        self._attr_unique_id = f"{self._unique_prefix}_debug"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.cover_results_for_controller(self._controller_id))

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        results = self.coordinator.cover_results_for_controller(self._controller_id)
        attrs: dict[str, str] = {}
        for result in results:
            decision = result.decision
            attrs[result.entity_id] = (
                f"reason={decision.reason.value}, position={decision.position}, "
                f"tilt={decision.tilt}, blocked={decision.blocked}"
            )
        return attrs


class WindowStatusSensor(ShutterEngineWindowEntity, SensorEntity):
    """Exposes ``sensor.<window>_status`` for a single cover."""

    _attr_translation_key = "status"
    _attr_icon = "mdi:window-shutter-cog"

    def __init__(
        self, coordinator: ShutterEngineCoordinator, subentry_id: str, display_name: str
    ) -> None:
        super().__init__(coordinator, subentry_id, display_name)
        self._attr_unique_id = f"{self._unique_prefix}_status"

    @property
    def native_value(self) -> str:
        result = self.coordinator.cover_result(self._subentry_id)
        return result.status_text if result else "idle"

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        result = self.coordinator.cover_result(self._subentry_id)
        if result is None:
            return {}
        decision = result.decision
        return {
            "reason": decision.reason.value,
            "position": str(decision.position),
            "tilt": str(decision.tilt),
            "blocked": str(decision.blocked),
        }
