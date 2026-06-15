"""The Shutter Engine integration.

A resolver-based custom component that replaces scattered shutter automations
with one central, per-cover state machine. See the engine subpackage for the
Home-Assistant-independent decision logic.

Home Assistant imports are performed lazily inside the entry points so that the
pure engine and config modules remain importable (and unit-testable) without a
Home Assistant installation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .const import DOMAIN, PLATFORMS, STORAGE_KEY, STORAGE_VERSION

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Shutter Engine from a config entry."""

    from .coordinator import ShutterEngineCoordinator

    coordinator = ShutterEngineCoordinator(hass, entry)
    await coordinator.async_initialize()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _bind_room_devices_to_areas(hass, entry, coordinator)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""

    await hass.config_entries.async_reload(entry.entry_id)


def _bind_room_devices_to_areas(hass: HomeAssistant, entry: ConfigEntry, coordinator: Any) -> None:
    """Hard-bind each room device to its Home Assistant area.

    The room devices are created lazily while the platforms set up, so by the
    time this runs they exist in the device registry. We explicitly assign the
    chosen ``area_id`` (rather than relying on ``suggested_area``) so the
    binding is authoritative.
    """

    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr

    ha_area_reg = ar.async_get(hass)
    dev_reg = dr.async_get(hass)
    for room in coordinator.rooms:
        area_id = room.area_id
        if not area_id or ha_area_reg.async_get_area(area_id) is None:
            continue  # no area selected or the area was deleted in HA
        device = dev_reg.async_get_device(
            identifiers={(DOMAIN, f"{entry.entry_id}_{area_id}")}
        )
        if device is not None and device.area_id != area_id:
            dev_reg.async_update_device(device.id, area_id=area_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate free-text room names (v1) to Home Assistant area ids (v2)."""

    if entry.version >= 2:
        return True

    from homeassistant.helpers import area_registry as ar

    ha_area_reg = ar.async_get(hass)
    # Case-insensitive index of existing area names -> area_id.
    name_index = {area.name.casefold(): area.id for area in ha_area_reg.async_list_areas()}
    # Legacy room name -> resolved area_id, used to remap the runtime store.
    name_to_area: dict[str, str] = {}

    def migrate_rooms(rooms: list[Any]) -> list[Any]:
        result: list[Any] = []
        used: set[str] = set()
        for room in rooms:
            if not isinstance(room, dict):
                result.append(room)
                continue
            area_id = room.get("area_id")
            legacy_name = room.get("name", "") or ""
            if not area_id:
                area_id = name_index.get(legacy_name.casefold())
                if not area_id:
                    area = ha_area_reg.async_get_or_create(
                        legacy_name or "Shutter Engine Room"
                    )
                    area_id = area.id
                    name_index[area.name.casefold()] = area.id
                room["area_id"] = area_id
            if area_id in used:
                _LOGGER.warning(
                    "Dropping duplicate room '%s' mapping to area %s", legacy_name, area_id
                )
                continue
            used.add(area_id)
            if legacy_name:
                name_to_area[legacy_name] = area_id
            result.append(room)
        return result

    new_data = dict(entry.data)
    new_options = dict(entry.options)
    if isinstance(new_data.get("rooms"), list):
        new_data["rooms"] = migrate_rooms(new_data["rooms"])
    if isinstance(new_options.get("rooms"), list):
        new_options["rooms"] = migrate_rooms(new_options["rooms"])

    await _migrate_runtime_store(hass, name_to_area)
    _migrate_registries(hass, entry, name_to_area)

    hass.config_entries.async_update_entry(
        entry, data=new_data, options=new_options, version=2
    )
    return True


async def _migrate_runtime_store(hass: HomeAssistant, name_to_area: dict[str, str]) -> None:
    """Re-key the persisted ``__rooms__`` toggles from room name to area id."""

    if not name_to_area:
        return

    from homeassistant.helpers.storage import Store

    store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    data = await store.async_load()
    if not data or "__rooms__" not in data:
        return

    remapped: dict[str, Any] = {}
    changed = False
    for key, value in data["__rooms__"].items():
        new_key = name_to_area.get(key, key)
        remapped[new_key] = value
        changed = changed or new_key != key
    if changed:
        data["__rooms__"] = remapped
        await store.async_save(data)


def _migrate_registries(
    hass: HomeAssistant, entry: ConfigEntry, name_to_area: dict[str, str]
) -> None:
    """Re-key entity unique_ids and device identifiers from name to area id."""

    if not name_to_area:
        return

    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    for name, area_id in name_to_area.items():
        old_prefix = f"{entry.entry_id}_{name}"
        new_prefix = f"{entry.entry_id}_{area_id}"
        if old_prefix == new_prefix:
            continue
        for ent in list(ent_reg.entities.values()):
            if ent.config_entry_id != entry.entry_id:
                continue
            if ent.unique_id == old_prefix or ent.unique_id.startswith(old_prefix + "_"):
                new_uid = new_prefix + ent.unique_id[len(old_prefix) :]
                ent_reg.async_update_entity(ent.entity_id, new_unique_id=new_uid)
        device = dev_reg.async_get_device(identifiers={(DOMAIN, old_prefix)})
        if device is not None:
            dev_reg.async_update_device(device.id, new_identifiers={(DOMAIN, new_prefix)})
