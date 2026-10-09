"""Sensors for Leave By."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BUFFER_MINUTES,
    CONF_COUNTDOWN_TYPE,
    CONF_TEXT_STYLE,
)
from .coordinator import LeaveByConfigEntry
from .entity import LeaveByEntity, TickingEntity
from .logic import format_countdown, seconds_until

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LeaveByConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            NextEventSensor(coordinator),
            LeaveByTimeSensor(coordinator),
            EventStartSensor(coordinator),
            TravelTimeSensor(coordinator),
            SecondsRemainingSensor(coordinator),
            CountdownTextSensor(coordinator),
        ]
    )


class NextEventSensor(LeaveByEntity, SensorEntity):
    """Name of the event currently being counted down to."""

    _unrecorded_attributes = frozenset({"upcoming"})

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "next_event")

    @property
    def native_value(self) -> str | None:
        ev = self.current_event
        return ev.summary if ev else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ev = self.current_event
        if ev is None:
            return {"skipped_events": self.coordinator.data.skipped if self.coordinator.data else []}
        now = dt_util.utcnow()
        cfg = self.coordinator.cfg
        return {
            "location": ev.location,
            "calendar": ev.calendar,
            "event_start": ev.start.isoformat(),
            "leave_by": ev.leave_by.isoformat() if ev.leave_by else None,
            "travel_mode": ev.mode,
            "travel_minutes": round((ev.travel_seconds or 0) / 60),
            "buffer_minutes": cfg[CONF_BUFFER_MINUTES],
            "countdown_type": cfg[CONF_COUNTDOWN_TYPE],
            "skipped_events": self.coordinator.data.skipped,
            "upcoming": [
                {
                    "event": e.summary,
                    "location": e.location,
                    "event_start": e.start.isoformat(),
                    "leave_by": e.leave_by.isoformat() if e.leave_by else None,
                }
                for e in self.coordinator.data.upcoming(now, self.coordinator.dismissed)[:5]
            ],
        }


class LeaveByTimeSensor(LeaveByEntity, SensorEntity):
    """Moment to leave."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "leave_by_time")

    @property
    def native_value(self) -> datetime | None:
        ev = self.current_event
        return ev.leave_by if ev else None


class EventStartSensor(LeaveByEntity, SensorEntity):
    """Start time of the event being counted down to."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "event_start")

    @property
    def native_value(self) -> datetime | None:
        ev = self.current_event
        return ev.start if ev else None


class TravelTimeSensor(LeaveByEntity, SensorEntity):
    """Current travel-time estimate."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "travel_time")

    @property
    def native_value(self) -> float | None:
        ev = self.current_event
        if ev is None or ev.travel_seconds is None:
            return None
        return round(ev.travel_seconds / 60, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ev = self.current_event
        if ev is None or ev.static_seconds is None:
            return {}
        return {"without_traffic_minutes": round(ev.static_seconds / 60, 1)}


class SecondsRemainingSensor(TickingEntity, SensorEntity):
    """Seconds until the countdown target (negative once late)."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "seconds_remaining")

    @property
    def native_value(self) -> int | None:
        ev = self.current_event
        if ev is None:
            return None
        target = self.coordinator.target_time(ev)
        return seconds_until(target, dt_util.utcnow()) if target else None


class CountdownTextSensor(TickingEntity, SensorEntity):
    """Countdown formatted as text (handy for native-app widgets)."""

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "countdown")

    @property
    def native_value(self) -> str | None:
        ev = self.current_event
        if ev is None:
            return "No trips"
        target = self.coordinator.target_time(ev)
        if target is None:
            return "No trips"
        seconds = seconds_until(target, dt_util.utcnow())
        return format_countdown(seconds, self.coordinator.cfg[CONF_TEXT_STYLE])
