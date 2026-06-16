"""The Shutter Engine integration.

A resolver-based custom component that replaces scattered shutter automations
with one central, per-cover state machine. See the engine subpackage for the
Home-Assistant-independent decision logic.

Configuration is split into config *subentries* (``ruleset`` / ``controller`` /
``window``); each controller and window subentry maps to its own device.

Home Assistant imports are performed lazily inside the entry points so that the
pure engine and config modules remain importable (and unit-testable) without a
Home Assistant installation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .const import DOMAIN, PLATFORMS

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
    _bind_devices_to_areas(hass, entry, coordinator)
    _cleanup_orphan_devices(hass, entry)
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
    """Reload the entry when its options or subentries change."""

    await hass.config_entries.async_reload(entry.entry_id)


def _bind_devices_to_areas(hass: HomeAssistant, entry: ConfigEntry, coordinator: Any) -> None:
    """Hard-bind each controller/window device to its Home Assistant area.

    The devices are created lazily while the platforms set up, so by the time
    this runs they exist in the device registry. We explicitly assign the
    chosen ``area_id`` (rather than relying on ``suggested_area``) so the
    binding is authoritative. Window devices follow their controller's area.
    """

    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr

    ha_area_reg = ar.async_get(hass)
    dev_reg = dr.async_get(hass)

    def bind(identifier: str, area_id: str) -> None:
        if not area_id or ha_area_reg.async_get_area(area_id) is None:
            return  # no area selected or the area was deleted in HA
        device = dev_reg.async_get_device(identifiers={(DOMAIN, identifier)})
        if device is not None and device.area_id != area_id:
            dev_reg.async_update_device(device.id, area_id=area_id)

    for controller_id in coordinator.controllers:
        bind(f"controller_{controller_id}", coordinator.controller_area_id(controller_id))

    for subentry_id in coordinator.window_ids():
        controller_id = coordinator.window_controller_id(subentry_id)
        if controller_id is not None:
            bind(f"window_{subentry_id}", coordinator.controller_area_id(controller_id))


def _cleanup_orphan_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove legacy devices that don't belong to any current subentry.

    Before the split into ruleset/controller/window subentries, devices were
    attached to the config entry directly. Those leftovers show up in Home
    Assistant as "devices not assigned to a subentry". Current devices are
    always linked to a live subentry via ``config_subentry_id`` at add time, so
    any config-entry device whose subentry link is missing (or points at a
    deleted subentry) is an orphan and is removed here.
    """

    from homeassistant.helpers import device_registry as dr

    dev_reg = dr.async_get(hass)
    valid_subentries = set(entry.subentries)

    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        subentry_ids = device.config_entries_subentries.get(entry.entry_id) or set()
        if subentry_ids & valid_subentries:
            continue  # still linked to a live subentry -> keep
        if len(device.config_entries) > 1:
            # Shared with another integration: only drop our own link.
            dev_reg.async_update_device(device.id, remove_config_entry_id=entry.entry_id)
        else:
            dev_reg.async_remove_device(device.id)
