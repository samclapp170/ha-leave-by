"""Helpers for integration tests."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.components import calendar
from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from custom_components.leave_by.api import RouteResult
from custom_components.leave_by.const import CONF_API_KEY, CONF_CALENDARS

CAL = "calendar.test"


class FakeCalendar(CalendarEntity):
    """A real calendar entity so calendar.get_events behaves like production."""

    _attr_name = "Test"

    def __init__(self, events: list[CalendarEvent]) -> None:
        self._events = events
        self.entity_id = CAL

    @property
    def event(self) -> CalendarEvent | None:
        return None

    async def async_get_events(self, hass, start_date, end_date):
        return [e for e in self._events if start_date <= e.start_datetime_local < end_date]


async def register_calendar(hass: HomeAssistant, events: list[CalendarEvent]) -> FakeCalendar:
    assert await async_setup_component(hass, "calendar", {})
    entity = FakeCalendar(events)
    await hass.data[calendar.DATA_COMPONENT].async_add_entities([entity])
    await hass.async_block_till_done()
    return entity


def make_event(minutes_from_now: float, summary="Dentist", location="1 Main St", uid="u1"):
    start = dt_util.utcnow() + timedelta(minutes=minutes_from_now)
    return CalendarEvent(
        start=start,
        end=start + timedelta(hours=1),
        summary=summary,
        location=location,
        uid=uid,
    )


def route_patch(minutes: float = 20, static: float | None = None):
    """Patch the Routes client to return a fixed travel time."""
    result = RouteResult(
        duration=int(minutes * 60), static_duration=int((static or minutes) * 60)
    )
    return patch(
        "custom_components.leave_by.coordinator.RoutesClient.compute",
        return_value=result,
    )


BASE_OPTIONS = {
    CONF_CALENDARS: [CAL],
}
BASE_DATA = {CONF_API_KEY: "test-key"}
