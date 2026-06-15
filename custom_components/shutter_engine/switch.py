"""Switch entities for per-controller control (lock, night, morning, holiday)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity

from .const import DOMAIN
from .coordinator import ControllerControls
from .entity import ShutterEngineControllerEntity, resolve_area_display

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ShutterEngineCoordinator


@dataclass(frozen=True, kw_only=True)
class ControllerSwitchDescription:
    """Describes one controller control switch."""

    key: str
    translation_key: str
    control_attr: str
    icon: str
    getter: Callable[[ControllerControls], bool]


SWITCHES: tuple[ControllerSwitchDescription, ...] = (
    ControllerSwitchDescription(
        key="lock",
        translation_key="lock",
        control_attr="locked",
        icon="mdi:lock",
        getter=lambda c: c.locked,
    ),
    ControllerSwitchDescription(
        key="night",
        translation_key="night",
        control_attr="night_enabled",
        icon="mdi:weather-night",
        getter=lambda c: c.night_enabled,
    ),
    ControllerSwitchDescription(
        key="morning",
        translation_key="morning",
        control_attr="morning_enabled",
        icon="mdi:weather-sunset-up",
        getter=lambda c: c.morning_enabled,
    ),
    ControllerSwitchDescription(
        key="holiday",
        translation_key="holiday",
        control_attr="holiday",
        icon="mdi:bag-suitcase",
        getter=lambda c: c.holiday,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the per-controller control switches."""

    coordinator: ShutterEngineCoordinator = hass.data[DOMAIN][entry.entry_id]
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != "controller":
            continue
        display = resolve_area_display(hass, subentry.data.get("area_id", ""), subentry.title)
        async_add_entities(
            [
                ControllerControlSwitch(coordinator, subentry_id, display, description)
                for description in SWITCHES
            ],
            config_subentry_id=subentry_id,
        )


class ControllerControlSwitch(ShutterEngineControllerEntity, SwitchEntity):
    """A single controller control switch."""

    def __init__(
        self,
        coordinator: ShutterEngineCoordinator,
        controller_id: str,
        display_name: str,
        description: ControllerSwitchDescription,
    ) -> None:
        super().__init__(coordinator, controller_id, display_name)
        self.entity_description = description  # type: ignore[assignment]
        self._description = description
        self._attr_translation_key = description.translation_key
        self._attr_icon = description.icon
        self._attr_unique_id = f"{self._unique_prefix}_{description.key}"

    @property
    def is_on(self) -> bool:
        return self._description.getter(self.coordinator.controller_controls(self._controller_id))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_controller_control(
            self._controller_id, **{self._description.control_attr: True}
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_controller_control(
            self._controller_id, **{self._description.control_attr: False}
        )
