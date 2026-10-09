"""Buttons for Leave By."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import TIER_LEAVE_NOW
from .coordinator import LeaveByConfigEntry
from .entity import LeaveByEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LeaveByConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            RefreshButton(coordinator),
            TestAlertButton(coordinator),
            DismissButton(coordinator),
        ]
    )


class RefreshButton(LeaveByEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "refresh")

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()


class TestAlertButton(LeaveByEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "test_alert")

    async def async_press(self) -> None:
        await self.coordinator.async_test_alert(TIER_LEAVE_NOW)


class DismissButton(LeaveByEntity, ButtonEntity):
    """Skip the current event — "I'm already in the car"."""

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "dismiss_event")

    async def async_press(self) -> None:
        await self.coordinator.async_dismiss_current()
