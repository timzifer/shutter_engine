"""DataUpdateCoordinator wiring Home Assistant state into the resolver.

The coordinator owns the per-cover runtime state (hysteresis, manual-override
pauses, last-movement timestamps) and persists it through the Home Assistant
store helper. On every relevant trigger it builds a :class:`ResolverInput` per
cover, runs :func:`resolve` and commands the cover.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    SERVICE_SET_COVER_POSITION,
    SERVICE_SET_COVER_TILT_POSITION,
)
from homeassistant.components.cover import (
    DOMAIN as COVER_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .config import parse_config
from .const import (
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .engine import (
    ContactState,
    DayMode,
    Decision,
    Hysteresis,
    ResolverInput,
    TemperatureHysteresis,
    estimate_brightness,
    in_sun_funnel,
    resolve,
    resolve_time_window,
    slat_tilt_for_elevation,
)
from .engine.models import ResolvedCoverConfig, resolve_cover_config

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .engine import AreaConfig, HubConfig, RoomConfig

_LOGGER = logging.getLogger(__name__)

# Tolerance for accepting our own movement as "cleanly executed" (concept §8).
_POSITION_TOLERANCE = 5  # percent
_EXECUTION_WINDOW = timedelta(minutes=3)
# Default duration a cover stays paused after a detected manual intervention.
_DEFAULT_PAUSE = timedelta(hours=2)


@dataclass
class CoverRuntime:
    """Transient per-cover state owned by the coordinator."""

    brightness_hysteresis: Hysteresis
    expected_position: int | None = None
    expected_until: datetime | None = None
    last_command_at: datetime | None = None
    last_target: int | None = None
    paused_until: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "brightness_active": self.brightness_hysteresis.active,
            "last_command_at": _iso(self.last_command_at),
            "last_target": self.last_target,
            "paused_until": _iso(self.paused_until),
        }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_iso(value: str | None) -> datetime | None:
    return dt_util.parse_datetime(value) if value else None


@dataclass
class CoverResult:
    """Resolved decision plus the diagnostic context for one cover."""

    decision: Decision
    status_text: str


@dataclass
class RoomControls:
    """User-facing, runtime-mutable room state driven by the room entities.

    Initialized from the room configuration defaults, then overridden by the
    ``select``/``switch`` entities and persisted across restarts.
    """

    day_mode: DayMode
    locked: bool
    night_enabled: bool
    morning_enabled: bool
    holiday: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "day_mode": self.day_mode.value,
            "locked": self.locked,
            "night_enabled": self.night_enabled,
            "morning_enabled": self.morning_enabled,
            "holiday": self.holiday,
        }


@dataclass
class _CoverNode:
    """A cover together with its resolved config and parent area/room."""

    config: ResolvedCoverConfig
    area: AreaConfig
    room: RoomConfig
    runtime: CoverRuntime = field(default=None)  # type: ignore[assignment]


class ShutterEngineCoordinator(DataUpdateCoordinator[dict[str, CoverResult]]):
    """Central resolver coordinator (one instance per config entry)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS),
        )
        self.entry = entry
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.hub: HubConfig
        self.rooms: list[RoomConfig]
        self._covers: dict[str, _CoverNode] = {}
        self._room_controls: dict[str, RoomControls] = {}
        self._unsub: list = []
        self._reload_config()

    # -- setup -------------------------------------------------------------

    def _reload_config(self) -> None:
        """(Re)build the cover tree from the config entry options."""

        data = {**self.entry.data, **self.entry.options}
        self.hub, self.rooms = parse_config(data)
        self._covers = {}
        for room in self.rooms:
            self._room_controls.setdefault(
                room.area_id,
                RoomControls(
                    day_mode=room.day_mode,
                    locked=room.locked,
                    night_enabled=room.night.enabled,
                    morning_enabled=room.morning.enabled,
                    holiday=room.holiday,
                ),
            )
            for area in room.areas:
                for cover in area.covers:
                    resolved = resolve_cover_config(cover, area, room, self.hub)
                    self._covers[resolved.entity_id] = _CoverNode(
                        config=resolved, area=area, room=room
                    )

    async def async_initialize(self) -> None:
        """Restore persisted state and subscribe to triggers."""

        stored = await self._store.async_load() or {}
        saved_rooms = stored.get("__rooms__", {})
        for area_id, controls in self._room_controls.items():
            saved_room = saved_rooms.get(area_id)
            if saved_room:
                controls.day_mode = DayMode(saved_room.get("day_mode", controls.day_mode))
                controls.locked = bool(saved_room.get("locked", controls.locked))
                controls.night_enabled = bool(
                    saved_room.get("night_enabled", controls.night_enabled)
                )
                controls.morning_enabled = bool(
                    saved_room.get("morning_enabled", controls.morning_enabled)
                )
                controls.holiday = bool(saved_room.get("holiday", controls.holiday))
        for entity_id, node in self._covers.items():
            saved = stored.get(entity_id, {})
            node.runtime = CoverRuntime(
                brightness_hysteresis=Hysteresis(
                    high=node.config.brightness_close,
                    low=node.config.brightness_open,
                    active=bool(saved.get("brightness_active", False)),
                ),
                last_command_at=_parse_iso(saved.get("last_command_at")),
                last_target=saved.get("last_target"),
                # paused flags are re-evaluated, never blindly restored (§8).
                paused_until=None,
            )
        self._subscribe()

    def _subscribe(self) -> None:
        tracked = self._tracked_entities()
        if tracked:
            self._unsub.append(
                async_track_state_change_event(self.hass, list(tracked), self._handle_state_change)
            )
        self._unsub.append(
            async_track_time_interval(
                self.hass, self._handle_tick, timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS)
            )
        )

    def _tracked_entities(self) -> set[str]:
        tracked: set[str] = set(self._covers)
        for entity in (
            self.hub.sun_entity,
            self.hub.weather_entity,
            self.hub.workday_entity,
            self.hub.wind_entity,
            self.hub.frost_entity,
            self.hub.fire_entity,
            self.hub.burglary_entity,
        ):
            if entity:
                tracked.add(entity)
        for node in self._covers.values():
            for entity in (
                node.area.brightness_entity,
                node.area.contact_entity,
                node.room.heating_entity,
                node.room.room_temp_entity,
            ):
                if entity:
                    tracked.add(entity)
        return tracked

    async def async_shutdown(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()
        await self._persist()

    # -- triggers ----------------------------------------------------------

    @callback
    def _handle_tick(self, _now: datetime) -> None:
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _handle_state_change(self, event) -> None:
        entity_id = event.data.get("entity_id")
        if entity_id in self._covers:
            self._detect_manual_intervention(entity_id, event.data.get("new_state"))
        self.hass.async_create_task(self.async_request_refresh())

    # -- manual intervention detection (§8) --------------------------------

    def _detect_manual_intervention(self, entity_id: str, new_state: State | None) -> None:
        """Flag a cover as paused when an external change is detected.

        Our own commands are tolerated within a position and time window; any
        other change counts as a manual intervention.
        """

        node = self._covers.get(entity_id)
        if node is None or new_state is None:
            return
        position = new_state.attributes.get(ATTR_POSITION)
        if position is None:
            return
        runtime = node.runtime
        now = dt_util.utcnow()

        if (
            runtime.expected_position is not None
            and runtime.expected_until is not None
            and now <= runtime.expected_until
            and abs(int(position) - runtime.expected_position) <= _POSITION_TOLERANCE
        ):
            # Cleanly executed own command -> clear expectation.
            runtime.expected_position = None
            runtime.expected_until = None
            return

        # External change -> pause automation for this cover.
        runtime.paused_until = now + _DEFAULT_PAUSE
        _LOGGER.debug("Manual intervention detected on %s, pausing", entity_id)

    # -- the update cycle --------------------------------------------------

    async def _async_update_data(self) -> dict[str, CoverResult]:
        now = dt_util.utcnow()
        results: dict[str, CoverResult] = {}
        for entity_id, node in self._covers.items():
            decision = self._resolve_cover(node, now)
            results[entity_id] = CoverResult(
                decision=decision,
                status_text=self._status_text(node, decision),
            )
            await self._apply_decision(node, decision, now)
        await self._persist()
        return results

    def _resolve_cover(self, node: _CoverNode, now: datetime) -> Decision:
        cfg = node.config
        runtime = node.runtime
        controls = self._room_controls[node.room.area_id]
        cover_state = self.hass.states.get(cfg.entity_id)
        current_position = self._state_position(cover_state)
        current_tilt = cover_state.attributes.get(ATTR_TILT_POSITION) if cover_state else None

        manual_override = bool(runtime.paused_until and now < runtime.paused_until)
        morning_due, night_due = self._time_window_due(node, controls)

        inp = ResolverInput(
            config=cfg,
            current_position=current_position,
            current_tilt=current_tilt,
            day_mode=controls.day_mode,
            locked=controls.locked,
            manual_override=manual_override,
            fire_active=self._is_on(self.hub.fire_entity),
            burglary_active=self._is_on(self.hub.burglary_entity),
            storm_active=self._is_on(self.hub.wind_entity),
            frost_active=self._is_on(self.hub.frost_entity),
            contact_state=self._contact_state(node.area.contact_entity),
            morning_due=morning_due,
            night_due=night_due,
            sun_in_funnel=self._sun_in_funnel(cfg),
            bright_enough=self._bright_enough(node),
            eco_temp_reached=self._eco_temp_reached(node),
            heat_over_max=self._heat_over_max(node),
            tracked_tilt=self._tracked_tilt(cfg),
            seconds_since_last_move=self._seconds_since_move(runtime, now),
        )
        return resolve(inp)

    def _tracked_tilt(self, cfg: ResolvedCoverConfig) -> int | None:
        """Compute the dynamic slat tilt from the current sun elevation.

        Returns ``None`` when tracking does not apply (cover can't tilt or has
        tracking disabled) or when no sun elevation is available; the resolver
        then keeps the statically configured tilt.
        """

        if not (cfg.slat_tracking and cfg.capabilities.can_tilt):
            return None
        attrs = self._sun_attrs()
        if attrs is None:
            return None
        _, elevation = attrs
        elevation_low = cfg.elevation_min if cfg.elevation_min is not None else 0.0
        elevation_high = cfg.elevation_max if cfg.elevation_max is not None else 90.0
        return slat_tilt_for_elevation(
            elevation,
            elevation_low=elevation_low,
            elevation_high=elevation_high,
        )

    def _time_window_due(self, node: _CoverNode, controls: RoomControls) -> tuple[bool, bool]:
        """Return ``(morning_due, night_due)`` from the time-window helper."""

        now_local = dt_util.now()
        morning_due = False
        night_due = False

        if controls.morning_enabled and node.room.morning.window_start:
            morning_due = self._window_due(
                now_local, node.room.morning, self._sun_event("next_rising")
            )
        if controls.night_enabled and node.room.night.window_start:
            night_due = self._window_due(
                now_local, node.room.night, self._sun_event("next_setting")
            )
        return morning_due, night_due

    def _window_due(self, now_local, fn, sun_event) -> bool:
        start = self._time_today(now_local, fn.window_start)
        end = self._time_today(now_local, fn.window_end)
        if start is None or end is None or end < start:
            return False
        rel = timedelta(minutes=fn.rel_offset) if fn.rel_offset else timedelta()
        result = resolve_time_window(
            now=now_local,
            window_start=start,
            window_end=end,
            sun_event=sun_event,
            rel_offset=rel,
        )
        return result.action_due

    def _time_today(self, reference, hhmm: str | None):
        if not hhmm:
            return None
        try:
            hour, minute = (int(part) for part in hhmm.split(":"))
        except (ValueError, AttributeError):
            return None
        return reference.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def _sun_event(self, attribute: str):
        if not self.hub.sun_entity:
            return None
        state = self.hass.states.get(self.hub.sun_entity)
        if state is None:
            return None
        value = state.attributes.get(attribute)
        parsed = dt_util.parse_datetime(value) if value else None
        return dt_util.as_local(parsed) if parsed else None

    # -- HA state helpers --------------------------------------------------

    def _state_position(self, state: State | None) -> int:
        if state is None:
            return 100
        position = state.attributes.get(ATTR_POSITION)
        if position is not None:
            return int(position)
        return 100 if state.state == "open" else 0

    def _is_on(self, entity_id: str | None) -> bool:
        if not entity_id:
            return False
        state = self.hass.states.get(entity_id)
        return bool(state and state.state == "on")

    def _contact_state(self, entity_id: str | None) -> ContactState:
        if not entity_id:
            return ContactState.CLOSED
        state = self.hass.states.get(entity_id)
        if state is None:
            return ContactState.CLOSED
        raw = state.state.lower()
        if raw in ("on", "open"):
            return ContactState.OPEN
        if raw == "tilted":
            return ContactState.TILTED
        return ContactState.CLOSED

    def _sun_attrs(self) -> tuple[float, float] | None:
        if not self.hub.sun_entity:
            return None
        state = self.hass.states.get(self.hub.sun_entity)
        if state is None:
            return None
        azimuth = state.attributes.get("azimuth")
        elevation = state.attributes.get("elevation")
        if azimuth is None or elevation is None:
            return None
        return float(azimuth), float(elevation)

    def _sun_in_funnel(self, cfg: ResolvedCoverConfig) -> bool:
        attrs = self._sun_attrs()
        if attrs is None:
            return False
        azimuth, elevation = attrs
        return in_sun_funnel(
            azimuth,
            elevation,
            cfg.azimuth_from,
            cfg.azimuth_to,
            cfg.elevation_min,
            cfg.elevation_max,
        )

    def _brightness(self, node: _CoverNode) -> float:
        entity_id = node.area.brightness_entity
        if entity_id:
            state = self.hass.states.get(entity_id)
            if state is not None and state.state not in ("unknown", "unavailable"):
                try:
                    return float(state.state)
                except ValueError:
                    pass
        # Fallback: estimate from sun elevation and cloud coverage.
        attrs = self._sun_attrs()
        if attrs is None:
            return 0.0
        _, elevation = attrs
        return estimate_brightness(elevation, self._cloud_coverage())

    def _cloud_coverage(self) -> float:
        if not self.hub.weather_entity:
            return 0.0
        state = self.hass.states.get(self.hub.weather_entity)
        if state is None:
            return 0.0
        cloud = state.attributes.get("cloud_coverage")
        if cloud is None:
            return 0.0
        try:
            return float(cloud) / 100.0
        except (TypeError, ValueError):
            return 0.0

    def _bright_enough(self, node: _CoverNode) -> bool:
        return node.runtime.brightness_hysteresis.update(self._brightness(node))

    def _temperature(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        value = state.attributes.get("current_temperature")
        if value is None:
            try:
                value = float(state.state)
            except (TypeError, ValueError):
                return None
        return float(value)

    def _eco_temp_reached(self, node: _CoverNode) -> bool:
        temp = self._temperature(node.room.heating_entity)
        if temp is None or node.room.target_temp is None:
            return True  # no eco data -> behave like plain sun protection
        hyst = TemperatureHysteresis(node.room.target_temp, node.config.temp_hysteresis)
        return hyst.update(temp)

    def _heat_over_max(self, node: _CoverNode) -> bool:
        temp = self._temperature(node.room.room_temp_entity)
        if temp is None or node.room.max_temp is None:
            return False
        hyst = TemperatureHysteresis(node.room.max_temp, node.config.temp_hysteresis)
        return hyst.update(temp)

    def _seconds_since_move(self, runtime: CoverRuntime, now: datetime) -> float | None:
        if runtime.last_command_at is None:
            return None
        return (now - runtime.last_command_at).total_seconds()

    # -- command output ----------------------------------------------------

    async def _apply_decision(self, node: _CoverNode, decision: Decision, now: datetime) -> None:
        cfg = node.config
        runtime = node.runtime
        state = self.hass.states.get(cfg.entity_id)
        current = self._state_position(state)
        current_tilt = state.attributes.get(ATTR_TILT_POSITION) if state else None

        tilt_changed = (
            decision.tilt is not None
            and cfg.capabilities.can_tilt
            and (current_tilt is None or int(current_tilt) != decision.tilt)
        )
        position_changed = not decision.blocked and decision.position != current

        if not position_changed and not tilt_changed:
            return

        if position_changed:
            await self.hass.services.async_call(
                COVER_DOMAIN,
                SERVICE_SET_COVER_POSITION,
                {ATTR_ENTITY_ID: cfg.entity_id, ATTR_POSITION: decision.position},
                blocking=False,
            )
        if tilt_changed:
            await self.hass.services.async_call(
                COVER_DOMAIN,
                SERVICE_SET_COVER_TILT_POSITION,
                {ATTR_ENTITY_ID: cfg.entity_id, ATTR_TILT_POSITION: decision.tilt},
                blocking=False,
            )

        runtime.last_command_at = now
        runtime.last_target = decision.position
        runtime.expected_position = decision.position
        runtime.expected_until = now + _EXECUTION_WINDOW

    # -- diagnostics & persistence ----------------------------------------

    def _status_text(self, node: _CoverNode, decision: Decision) -> str:
        attrs = self._sun_attrs()
        azimuth = f", az {attrs[0]:.0f}°" if attrs else ""
        brightness = self._brightness(node)
        klx = f", {brightness / 1000:.0f} klx" if brightness else ""
        return f"{decision.position}% — {decision.reason.value}{azimuth}{klx}"

    async def _persist(self) -> None:
        data: dict[str, Any] = {
            entity_id: node.runtime.as_dict()
            for entity_id, node in self._covers.items()
            if node.runtime is not None
        }
        data["__rooms__"] = {
            area_id: controls.as_dict() for area_id, controls in self._room_controls.items()
        }
        await self._store.async_save(data)

    # -- room control API (used by the room entities) ----------------------

    def room_controls(self, area_id: str) -> RoomControls:
        return self._room_controls[area_id]

    def cover_results_for_room(self, area_id: str) -> list[CoverResult]:
        results = self.data or {}
        return [
            results[entity_id]
            for entity_id, node in self._covers.items()
            if node.room.area_id == area_id and entity_id in results
        ]

    async def async_set_room_control(self, area_id: str, **changes: Any) -> None:
        """Apply a runtime control change for a room and re-resolve."""

        controls = self._room_controls[area_id]
        for key, value in changes.items():
            setattr(controls, key, value)
        await self._persist()
        await self.async_request_refresh()
