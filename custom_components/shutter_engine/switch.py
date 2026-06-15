"""Switch entities for per-room control (lock, night, morning, holiday)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity

from .const import DOMAIN
from .coordinator import RoomControls
from .entity import ShutterEngineRoomEntity, resolve_room_display

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ShutterEngineCoordinator


@dataclass(frozen=True, kw_only=True)
class RoomSwitchDescription:
    """Describes one room control switch."""

    key: str
    translation_key: str
    control_attr: str
    icon: str
    getter: Callable[[RoomControls], bool]


SWITCHES: tuple[RoomSwitchDescription, ...] = (
    RoomSwitchDescription(
        key="lock",
        translation_key="lock",
        control_attr="locked",
        icon="mdi:lock",
        getter=lambda c: c.locked,
    ),
    RoomSwitchDescription(
        key="night",
        translation_key="night",
        control_attr="night_enabled",
        icon="mdi:weather-night",
        getter=lambda c: c.night_enabled,
    ),
    RoomSwitchDescription(
        key="morning",
        translation_key="morning",
        control_attr="morning_enabled",
        icon="mdi:weather-sunset-up",
        getter=lambda c: c.morning_enabled,
    ),
    RoomSwitchDescription(
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
    """Set up the per-room control switches."""

    coordinator: ShutterEngineCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        RoomControlSwitch(
            coordinator,
            room.area_id,
            resolve_room_display(hass, room.area_id, room.name or room.area_id),
            description,
        )
        for room in coordinator.rooms
        for description in SWITCHES
    )


class RoomControlSwitch(ShutterEngineRoomEntity, SwitchEntity):
    """A single room control switch."""

    def __init__(
        self,
        coordinator: ShutterEngineCoordinator,
        area_id: str,
        display_name: str,
        description: RoomSwitchDescription,
    ) -> None:
        super().__init__(coordinator, area_id, display_name)
        self.entity_description = description  # type: ignore[assignment]
        self._description = description
        self._attr_translation_key = description.translation_key
        self._attr_icon = description.icon
        self._attr_unique_id = f"{self._unique_prefix}_{description.key}"

    @property
    def is_on(self) -> bool:
        return self._description.getter(self.coordinator.room_controls(self._area_id))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_room_control(
            self._area_id, **{self._description.control_attr: True}
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_room_control(
            self._area_id, **{self._description.control_attr: False}
        )
