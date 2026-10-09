"""Base entity for Leave By."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_TICK_SECONDS, DOMAIN, NAME
from .coordinator import LeaveByCoordinator, TripEvent


class LeaveByEntity(CoordinatorEntity[LeaveByCoordinator]):
    """Common device info + helpers."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: LeaveByCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=NAME,
            model="Calendar travel countdown",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def current_event(self) -> TripEvent | None:
        """The event being counted down to right now."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.current(
            dt_util.utcnow(), self.coordinator.dismissed
        )


class TickingEntity(LeaveByEntity):
    """Entity that re-renders locally every few seconds (no API calls)."""

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        seconds = max(1, int(self.coordinator.cfg[CONF_TICK_SECONDS]))
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._handle_tick, timedelta(seconds=seconds)
            )
        )

    @callback
    def _handle_tick(self, _now) -> None:
        self.async_write_ha_state()
