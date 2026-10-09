"""Diagnostics for Leave By."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_API_KEY, CONF_ORIGIN_ADDRESS
from .coordinator import LeaveByConfigEntry

TO_REDACT = {CONF_API_KEY, CONF_ORIGIN_ADDRESS, "location", "summary", "event"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LeaveByConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "config": async_redact_data({**entry.data, **entry.options}, TO_REDACT),
        "event_count": len(data.events) if data else 0,
        "skipped_count": len(data.skipped) if data else 0,
        "last_updated": data.updated.isoformat() if data and data.updated else None,
        "dismissed_count": len(coordinator.dismissed),
    }
