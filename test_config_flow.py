"""The setup interview and options menu."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.leave_by.api import (
    RouteResult,
    RoutesApiDisabled,
    RoutesConnectionError,
    RoutesInvalidKey,
    RoutesPermissionDenied,
)
from custom_components.leave_by.const import (
    CONF_API_KEY,
    CONF_BUFFER_MINUTES,
    CONF_CALENDARS,
    CONF_LIGHTS,
    CONF_SPEAKERS,
    CONF_TEST_ON_SETUP,
    CONF_TTS_ENTITY,
    DOMAIN,
)

from .common import CAL, make_event, register_calendar, route_patch

CHECK = "custom_components.leave_by.config_flow.RoutesClient.compute"
OK = RouteResult(600, 600)


async def _start(hass: HomeAssistant):
    await register_calendar(hass, [])
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result


async def test_aborts_without_calendars(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_calendars"


async def test_full_interview(hass: HomeAssistant) -> None:
    result = await _start(hass)
    flow = hass.config_entries.flow
    hass.states.async_set("tts.google_translate_en_com", "unknown")

    result = await flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "api_key"

    with patch(CHECK, return_value=OK):
        result = await flow.async_configure(result["flow_id"], {CONF_API_KEY: " abc123 "})
    assert result["step_id"] == "calendars"

    result = await flow.async_configure(
        result["flow_id"],
        {CONF_CALENDARS: [CAL], "lookahead_hours": 6, "poll_minutes": 15},
    )
    assert result["step_id"] == "trip"

    result = await flow.async_configure(
        result["flow_id"],
        {
            CONF_BUFFER_MINUTES: 5,
            "travel_mode": "DRIVE",
            "live_traffic": True,
            "origin_type": "address",
        },
    )
    assert result["step_id"] == "origin_detail"
    result = await flow.async_configure(
        result["flow_id"], {"origin_address": "100 Peachtree St, Atlanta"}
    )
    assert result["step_id"] == "countdown"

    result = await flow.async_configure(
        result["flow_id"],
        {"countdown_type": "event_start", "text_style": "friendly", "tick_seconds": 10},
    )
    assert result["step_id"] == "alerts"
    result = await flow.async_configure(
        result["flow_id"], {"heads_up_minutes": 20, "late_minutes": 5}
    )
    assert result["step_id"] == "lights"

    result = await flow.async_configure(
        result["flow_id"],
        {
            CONF_LIGHTS: ["light.hall"],
            "flash_length": "short",
            "flash_count": 2,
            "color_heads_up": [255, 255, 0],
            "color_leave_now": [0, 255, 0],
            "color_late": [255, 0, 0],
        },
    )
    assert result["step_id"] == "speakers"
    # The first TTS engine is pre-filled for convenience.
    schema_keys = {str(k): k for k in result["data_schema"].schema}
    assert (
        schema_keys[CONF_TTS_ENTITY].description["suggested_value"]
        == "tts.google_translate_en_com"
    )

    result = await flow.async_configure(
        result["flow_id"],
        {
            CONF_SPEAKERS: ["media_player.homepods"],
            CONF_TTS_ENTITY: "tts.google_translate_en_com",
            "volume": 40,
            "message_heads_up": "Heads up {event}",
            "message_leave_now": "Go to {event}",
            "message_late": "Late for {event}",
        },
    )
    # No notify services registered -> that page is skipped automatically.
    assert result["step_id"] == "confirm"

    result = await flow.async_configure(
        result["flow_id"], {"name": "Leave By", "run_test": True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Leave By"
    assert result["data"] == {CONF_API_KEY: "abc123", CONF_TEST_ON_SETUP: True}
    opts = result["options"]
    assert opts[CONF_CALENDARS] == [CAL]
    assert opts["lookahead_hours"] == 6
    assert opts[CONF_BUFFER_MINUTES] == 5
    assert opts["origin_address"] == "100 Peachtree St, Atlanta"
    assert opts["countdown_type"] == "event_start"
    assert opts["flash_count"] == 2
    assert opts["color_heads_up"] == [255, 255, 0]
    assert opts["volume"] == 40
    assert "origin_entity" not in opts


async def test_home_origin_skips_detail_step(hass: HomeAssistant) -> None:
    result = await _start(hass)
    flow = hass.config_entries.flow
    result = await flow.async_configure(result["flow_id"], {})
    with patch(CHECK, return_value=OK):
        result = await flow.async_configure(result["flow_id"], {CONF_API_KEY: "k"})
    result = await flow.async_configure(result["flow_id"], {CONF_CALENDARS: [CAL], "lookahead_hours": 4, "poll_minutes": 10})
    result = await flow.async_configure(
        result["flow_id"],
        {CONF_BUFFER_MINUTES: 5, "travel_mode": "WALK", "live_traffic": False, "origin_type": "home"},
    )
    assert result["step_id"] == "countdown"


@pytest.mark.parametrize(
    ("exc", "error"),
    [
        (RoutesInvalidKey("bad"), "invalid_api_key"),
        (RoutesApiDisabled("off"), "api_not_enabled"),
        (RoutesPermissionDenied("nope"), "permission_denied"),
        (RoutesConnectionError("down"), "cannot_connect"),
    ],
)
async def test_api_key_errors_and_recovery(hass: HomeAssistant, exc, error) -> None:
    result = await _start(hass)
    flow = hass.config_entries.flow
    result = await flow.async_configure(result["flow_id"], {})

    with patch(CHECK, side_effect=exc):
        result = await flow.async_configure(result["flow_id"], {CONF_API_KEY: "k"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "api_key"
    assert result["errors"] == {CONF_API_KEY: error}

    with patch(CHECK, return_value=OK):
        result = await flow.async_configure(result["flow_id"], {CONF_API_KEY: "good"})
    assert result["step_id"] == "calendars"


async def test_calendar_required(hass: HomeAssistant) -> None:
    result = await _start(hass)
    flow = hass.config_entries.flow
    result = await flow.async_configure(result["flow_id"], {})
    with patch(CHECK, return_value=OK):
        result = await flow.async_configure(result["flow_id"], {CONF_API_KEY: "k"})
    result = await flow.async_configure(
        result["flow_id"], {CONF_CALENDARS: [], "lookahead_hours": 4, "poll_minutes": 10}
    )
    assert result["errors"] == {CONF_CALENDARS: "no_calendars_selected"}


async def test_speakers_need_tts(hass: HomeAssistant) -> None:
    result = await _start(hass)
    flow = hass.config_entries.flow
    result = await flow.async_configure(result["flow_id"], {})
    with patch(CHECK, return_value=OK):
        result = await flow.async_configure(result["flow_id"], {CONF_API_KEY: "k"})
    result = await flow.async_configure(result["flow_id"], {CONF_CALENDARS: [CAL], "lookahead_hours": 4, "poll_minutes": 10})
    result = await flow.async_configure(result["flow_id"], {CONF_BUFFER_MINUTES: 5, "travel_mode": "DRIVE", "live_traffic": True, "origin_type": "home"})
    result = await flow.async_configure(result["flow_id"], {"countdown_type": "leave_by", "text_style": "clock", "tick_seconds": 15})
    result = await flow.async_configure(result["flow_id"], {"heads_up_minutes": 30, "late_minutes": 0})
    result = await flow.async_configure(result["flow_id"], {"flash_length": "long", "flash_count": 1, "color_heads_up": [255, 170, 0], "color_leave_now": [0, 255, 0], "color_late": [255, 0, 0]})
    assert result["step_id"] == "speakers"
    result = await flow.async_configure(
        result["flow_id"],
        {
            CONF_SPEAKERS: ["media_player.x"],
            "volume": 0,
            "message_heads_up": "a",
            "message_leave_now": "b",
            "message_late": "c",
        },
    )
    assert result["errors"] == {CONF_TTS_ENTITY: "tts_required"}


async def test_skipping_lights_speakers_creates_quiet_tracker(hass: HomeAssistant) -> None:
    result = await _start(hass)
    flow = hass.config_entries.flow
    result = await flow.async_configure(result["flow_id"], {})
    with patch(CHECK, return_value=OK):
        result = await flow.async_configure(result["flow_id"], {CONF_API_KEY: "k"})
    result = await flow.async_configure(result["flow_id"], {CONF_CALENDARS: [CAL], "lookahead_hours": 4, "poll_minutes": 10})
    result = await flow.async_configure(result["flow_id"], {CONF_BUFFER_MINUTES: 5, "travel_mode": "DRIVE", "live_traffic": True, "origin_type": "home"})
    result = await flow.async_configure(result["flow_id"], {"countdown_type": "leave_by", "text_style": "clock", "tick_seconds": 15})
    result = await flow.async_configure(result["flow_id"], {"heads_up_minutes": 30, "late_minutes": 0})
    result = await flow.async_configure(result["flow_id"], {"flash_length": "long", "flash_count": 1, "color_heads_up": [255, 170, 0], "color_leave_now": [0, 255, 0], "color_late": [255, 0, 0]})
    result = await flow.async_configure(result["flow_id"], {"volume": 0, "message_heads_up": "a", "message_leave_now": "b", "message_late": "c"})
    assert result["step_id"] == "confirm"
    result = await flow.async_configure(result["flow_id"], {"name": "Trips", "run_test": False})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_LIGHTS not in result["options"]
    assert CONF_TEST_ON_SETUP not in result["data"]


async def test_options_menu_changes_buffer(hass: HomeAssistant) -> None:
    await register_calendar(hass, [make_event(90)])
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Leave By",
        data={CONF_API_KEY: "k"},
        options={CONF_CALENDARS: [CAL], CONF_BUFFER_MINUTES: 5},
    )
    entry.add_to_hass(hass)
    with route_patch(20):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.MENU
        assert "finish" in result["menu_options"]

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "trip"}
        )
        assert result["step_id"] == "trip"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_BUFFER_MINUTES: 12, "travel_mode": "DRIVE", "live_traffic": True, "origin_type": "home"},
        )
        assert result["type"] is FlowResultType.MENU
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "finish"}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()

    assert entry.options[CONF_BUFFER_MINUTES] == 12
    assert entry.options[CONF_CALENDARS] == [CAL]
