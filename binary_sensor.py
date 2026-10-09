"""Binary sensors for Leave By."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import LeaveByConfigEntry
from .entity import LeaveByEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LeaveByConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([TimeToLeaveBinarySensor(entry.runtime_data)])


class TimeToLeaveBinarySensor(LeaveByEntity, BinarySensorEntity):
    """On from the leave-by moment until the event starts."""

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "time_to_leave")

    @property
    def is_on(self) -> bool:
        ev = self.current_event
        if ev is None or ev.leave_by is None:
            return False
        return ev.leave_by <= dt_util.utcnow() < ev.start
