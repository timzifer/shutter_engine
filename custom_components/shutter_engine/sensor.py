"""Diagnostic status sensors per controller and per window."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .engine.const import DecisionReason
from .entity import (
    ShutterEngineControllerEntity,
    ShutterEngineWindowEntity,
    resolve_area_display,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import CoverMemberResult, ShutterEngineCoordinator

_LOGGER = logging.getLogger(__name__)

_DECISION_REASON_OPTIONS: list[str] = [r.value for r in DecisionReason]


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
            batch = [
                    ControllerStatusSensor(coordinator, subentry_id, display),
                    ControllerDebugSensor(coordinator, subentry_id, display),
                    ControllerReasonSensor(coordinator, subentry_id, display),
                    ControllerTraceSensor(coordinator, subentry_id, display),
            ]
            _LOGGER.debug(
                "Creating %d sensor entities for controller %s (%s)",
                len(batch),
                subentry_id,
                display,
            )
            async_add_entities(batch, config_subentry_id=subentry_id)
        elif subentry.subentry_type == "window" and subentry_id in managed_windows:
            async_add_entities(
                [WindowStatusSensor(coordinator, subentry_id, subentry.title)],
                config_subentry_id=subentry_id,
            )


class ControllerStatusSensor(ShutterEngineControllerEntity, SensorEntity):
    """Exposes ``sensor.<controller>_status`` with a per-cover diagnostic text."""

    _attr_translation_key = "status"
    _attr_icon = "mdi:window-shutter-cog"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: ShutterEngineCoordinator, controller_id: str, display_name: str
    ) -> None:
        super().__init__(coordinator, controller_id, display_name)
        self._attr_unique_id = f"{self._unique_prefix}_status"

    @property
    def native_value(self) -> str:
        members = [
            member
            for result in self.coordinator.cover_results_for_controller(self._controller_id)
            for member in result.members
        ]
        if not members:
            return "idle"
        # Summarize with the most relevant (first) cover; details in attributes.
        return members[0].status_text

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {
            member.entity_id: member.status_text
            for result in self.coordinator.cover_results_for_controller(self._controller_id)
            for member in result.members
        }


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
        return sum(
            len(result.members)
            for result in self.coordinator.cover_results_for_controller(self._controller_id)
        )

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        results = self.coordinator.cover_results_for_controller(self._controller_id)
        attrs: dict[str, str] = {}
        for result in results:
            for member in result.members:
                decision = member.decision
                trace = member.trace
                applied = [c.name for c in trace.constraints if c.applied] or ["none"]
                detail = (
                    f"rule={trace.selected_driver}, final={trace.final_reason.value}, "
                    f"position={decision.position}, tilt={decision.tilt}, "
                    f"blocked={decision.blocked}, constraints={','.join(applied)}"
                )
                if trace.fire_bypassed_constraints:
                    detail += ", fire_bypass"
                attrs[member.entity_id] = detail
        return attrs


class ControllerReasonSensor(ShutterEngineControllerEntity, SensorEntity):
    """Enum sensor exposing the primary decision reason of this controller."""

    _attr_translation_key = "reason"
    _attr_icon = "mdi:list-status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = _DECISION_REASON_OPTIONS

    def __init__(
        self, coordinator: ShutterEngineCoordinator, controller_id: str, display_name: str
    ) -> None:
        super().__init__(coordinator, controller_id, display_name)
        self._attr_unique_id = f"{self._unique_prefix}_reason"

    def _all_members(self) -> list[CoverMemberResult]:
        return [
            member
            for result in self.coordinator.cover_results_for_controller(self._controller_id)
            for member in result.members
        ]

    @property
    def native_value(self) -> str | None:
        members = self._all_members()
        if not members:
            return DecisionReason.HOLD.value
        return members[0].decision.reason.value

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {
            member.entity_id: member.decision.reason.value
            for member in self._all_members()
        }


class ControllerTraceSensor(ShutterEngineControllerEntity, SensorEntity):
    """Structured trace sensor with individual driver and constraint results."""

    _attr_translation_key = "trace"
    _attr_icon = "mdi:file-tree"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: ShutterEngineCoordinator, controller_id: str, display_name: str
    ) -> None:
        super().__init__(coordinator, controller_id, display_name)
        self._attr_unique_id = f"{self._unique_prefix}_trace"

    def _all_members(self) -> list[CoverMemberResult]:
        return [
            member
            for result in self.coordinator.cover_results_for_controller(self._controller_id)
            for member in result.members
        ]

    @property
    def native_value(self) -> str:
        members = self._all_members()
        if not members:
            return "idle"
        trace = members[0].trace
        return trace.selected_driver

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        members = self._all_members()
        if not members:
            return {}

        attrs: dict[str, Any] = {}
        for member in members:
            trace = member.trace
            decision = member.decision
            drivers = {d.name: d.matched for d in trace.drivers}
            constraints = {
                c.name: {"applied": c.applied, "effect": c.effect}
                for c in trace.constraints
            }
            attrs[member.entity_id] = {
                "selected_driver": trace.selected_driver,
                "reason": trace.final_reason.value,
                "position": decision.position,
                "tilt": decision.tilt,
                "blocked": decision.blocked,
                "fire_bypass": trace.fire_bypassed_constraints,
                "drivers": drivers,
                "constraints": constraints,
            }
        return attrs


class WindowStatusSensor(ShutterEngineWindowEntity, SensorEntity):
    """Exposes ``sensor.<window>_status`` summarizing the surface's covers."""

    _attr_translation_key = "status"
    _attr_icon = "mdi:window-shutter-cog"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: ShutterEngineCoordinator, subentry_id: str, display_name: str
    ) -> None:
        super().__init__(coordinator, subentry_id, display_name)
        self._attr_unique_id = f"{self._unique_prefix}_status"

    @property
    def native_value(self) -> str:
        result = self.coordinator.cover_result(self._subentry_id)
        if result is None or not result.members:
            return "idle"
        if len(result.members) == 1:
            return result.members[0].status_text
        return f"{len(result.members)} covers — {result.members[0].status_text}"

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        result = self.coordinator.cover_result(self._subentry_id)
        if result is None:
            return {}
        return {
            member.entity_id: (
                f"reason={member.decision.reason.value}, "
                f"position={member.decision.position}, tilt={member.decision.tilt}, "
                f"blocked={member.decision.blocked}"
            )
            for member in result.members
        }
