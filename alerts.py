"""Alert actions: flash lights, speak on speakers, send notifications.

Every action is independent and failure-tolerant: one flaky speaker or an
offline phone never prevents the lights from flashing or the other alerts
from going out.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    CONF_COLOR_HEADS_UP,
    CONF_COLOR_LATE,
    CONF_COLOR_LEAVE_NOW,
    CONF_FLASH_COUNT,
    CONF_FLASH_LENGTH,
    CONF_LIGHTS,
    CONF_MSG_HEADS_UP,
    CONF_MSG_LATE,
    CONF_MSG_LEAVE_NOW,
    CONF_NOTIFY,
    CONF_SPEAKERS,
    CONF_TTS_ENTITY,
    CONF_VOLUME,
    EVENT_ALERT,
    FLASH_SECONDS,
    TIER_HEADS_UP,
    TIER_LATE,
    TIER_LEAVE_NOW,
)
from .logic import render_message, round_minutes

if TYPE_CHECKING:
    from .coordinator import TripEvent

_LOGGER = logging.getLogger(__name__)

TTS_RETRY_DELAY = 5

_COLOR_KEY = {
    TIER_HEADS_UP: CONF_COLOR_HEADS_UP,
    TIER_LEAVE_NOW: CONF_COLOR_LEAVE_NOW,
    TIER_LATE: CONF_COLOR_LATE,
}
_MSG_KEY = {
    TIER_HEADS_UP: CONF_MSG_HEADS_UP,
    TIER_LEAVE_NOW: CONF_MSG_LEAVE_NOW,
    TIER_LATE: CONF_MSG_LATE,
}


def _local_clock(value: datetime) -> str:
    local = dt_util.as_local(value)
    return local.strftime("%I:%M %p").lstrip("0")


def build_context(event: TripEvent, now: datetime) -> dict[str, Any]:
    """Values available to message templates."""
    leave_by = event.leave_by
    until = (leave_by - now).total_seconds() if leave_by else 0
    return {
        "event": event.summary,
        "location": event.location,
        "minutes": round_minutes(max(until, 0)),
        "minutes_late": round_minutes(max(-until, 0)),
        "travel_minutes": round_minutes(event.travel_seconds or 0),
        "leave_time": _local_clock(leave_by) if leave_by else "",
        "start_time": _local_clock(event.start),
    }


async def async_dispatch_alert(
    hass: HomeAssistant,
    cfg: dict[str, Any],
    tier: str,
    event: TripEvent,
    now: datetime,
) -> None:
    """Fire the bus event and run every configured alert action."""
    context = build_context(event, now)
    message = render_message(cfg[_MSG_KEY[tier]], context)

    hass.bus.async_fire(
        EVENT_ALERT,
        {
            "tier": tier,
            "message": message,
            **{k: v for k, v in context.items()},
            "leave_by": event.leave_by.isoformat() if event.leave_by else None,
            "event_start": event.start.isoformat(),
            "calendar": event.calendar,
        },
    )

    tasks = []
    if cfg.get(CONF_LIGHTS):
        tasks.append(_flash_lights(hass, cfg, tier))
    if cfg.get(CONF_SPEAKERS) and cfg.get(CONF_TTS_ENTITY):
        tasks.append(_speak(hass, cfg, message))
    for service in cfg.get(CONF_NOTIFY) or []:
        tasks.append(_notify(hass, service, event.summary, message))

    if not tasks:
        return
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            _LOGGER.warning("A Leave By alert action failed: %s", result)


async def _flash_lights(hass: HomeAssistant, cfg: dict[str, Any], tier: str) -> None:
    length = cfg[CONF_FLASH_LENGTH]
    count = max(1, int(cfg[CONF_FLASH_COUNT]))
    rgb = [int(c) for c in cfg[_COLOR_KEY[tier]]]
    for i in range(count):
        await hass.services.async_call(
            "light",
            "turn_on",
            {"entity_id": cfg[CONF_LIGHTS], "rgb_color": rgb, "flash": length},
            blocking=True,
        )
        if i < count - 1:
            # Let the previous flash finish before starting the next one.
            await asyncio.sleep(FLASH_SECONDS[length] + 1)


async def _speak(hass: HomeAssistant, cfg: dict[str, Any], message: str) -> None:
    speakers = cfg[CONF_SPEAKERS]
    volume = float(cfg.get(CONF_VOLUME) or 0)
    if volume > 0:
        try:
            await hass.services.async_call(
                "media_player",
                "volume_set",
                {"entity_id": speakers, "volume_level": min(volume, 100) / 100},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001 - never let volume block the announcement
            _LOGGER.warning("Could not set speaker volume: %s", err)

    data = {
        "entity_id": cfg[CONF_TTS_ENTITY],
        "media_player_entity_id": speakers,
        "message": message,
        "cache": True,
    }
    try:
        await hass.services.async_call("tts", "speak", data, blocking=True)
    except Exception as err:  # noqa: BLE001
        # Streaming to speaker groups (e.g. AirPlay) can fail transiently.
        _LOGGER.warning("TTS announcement failed (%s); retrying once", err)
        await asyncio.sleep(TTS_RETRY_DELAY)
        await hass.services.async_call("tts", "speak", data, blocking=True)


async def _notify(
    hass: HomeAssistant, service: str, title: str, message: str
) -> None:
    await hass.services.async_call(
        "notify",
        service,
        {"title": f"Leave for {title}", "message": message},
        blocking=True,
    )
