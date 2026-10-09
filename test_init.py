"""Setup, sensors, alerts and persistence."""

from __future__ import annotations

from datetime import date, timedelta

from homeassistant.components.calendar import CalendarEvent
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.leave_by.const import (
    CONF_BUFFER_MINUTES,
    CONF_COUNTDOWN_TYPE,
    CONF_HEADS_UP_MINUTES,
    CONF_LIGHTS,
    CONF_NOTIFY,
    CONF_SPEAKERS,
    CONF_TTS_ENTITY,
    DOMAIN,
    EVENT_ALERT,
)

from .common import BASE_DATA, BASE_OPTIONS, make_event, register_calendar, route_patch


def _entry(**opts) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Leave By",
        data=dict(BASE_DATA),
        options={**BASE_OPTIONS, **opts},
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def _advance(hass: HomeAssistant, freezer, **delta) -> None:
    freezer.tick(timedelta(**delta))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _state(hass, suffix):
    ids = [s for s in hass.states.async_entity_ids() if s.endswith(suffix)]
    assert ids, f"no entity ending with {suffix}"
    return hass.states.get(ids[0])


async def test_sensors_show_leave_by_with_car_buffer(hass: HomeAssistant) -> None:
    """Event in 90 min, 20 min drive, 5 min buffer -> leave in ~65 min."""
    await register_calendar(hass, [make_event(90)])
    with route_patch(20):
        await _setup(hass, _entry(**{CONF_BUFFER_MINUTES: 5}))

    assert _state(hass, "_next_event").state == "Dentist"
    assert float(_state(hass, "_travel_time").state) == 20.0
    remaining = int(_state(hass, "_seconds_remaining").state)
    assert 64 * 60 <= remaining <= 65 * 60
    assert _state(hass, "_countdown").state.startswith("64:") or _state(
        hass, "_countdown"
    ).state.startswith("1:04:")
    assert _state(hass, "_time_to_leave").state == "off"


async def test_countdown_to_event_start(hass: HomeAssistant) -> None:
    await register_calendar(hass, [make_event(90)])
    with route_patch(20):
        await _setup(hass, _entry(**{CONF_COUNTDOWN_TYPE: "event_start"}))
    remaining = int(_state(hass, "_seconds_remaining").state)
    assert 89 * 60 <= remaining <= 90 * 60


async def test_ignores_all_day_virtual_and_locationless(hass: HomeAssistant) -> None:
    events = [
        CalendarEvent(start=date.today() + timedelta(days=1), end=date.today() + timedelta(days=2), summary="All day", location="x"),
        make_event(60, "Zoom call", "https://zoom.us/j/1", "u2"),
        make_event(60, "No place", "", "u3"),
        make_event(120, "Real", "9 Elm St", "u4"),
    ]
    await register_calendar(hass, events)
    with route_patch(10):
        await _setup(hass, _entry())
    assert _state(hass, "_next_event").state == "Real"


async def test_no_events_gives_unknown_and_friendly_text(hass: HomeAssistant) -> None:
    await register_calendar(hass, [])
    with route_patch():
        await _setup(hass, _entry())
    assert _state(hass, "_next_event").state == "unknown"
    assert _state(hass, "_countdown").state == "No trips"


async def test_leave_now_alert_flashes_lights_and_speaks_once(hass: HomeAssistant, freezer) -> None:
    """Alert fires at the exact leave-by time, and not again on later refreshes."""
    lights = async_mock_service(hass, "light", "turn_on")
    tts = async_mock_service(hass, "tts", "speak")
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    fired = []
    hass.bus.async_listen(EVENT_ALERT, lambda e: fired.append(e))

    # Event in 45 min, 30 min drive, 5 min buffer -> leave in 10 min.
    await register_calendar(hass, [make_event(45)])
    entry = _entry(
        **{
            CONF_LIGHTS: ["light.hall"],
            CONF_SPEAKERS: ["media_player.kitchen"],
            CONF_TTS_ENTITY: "tts.test",
            CONF_NOTIFY: ["mobile_app_phone"],
            CONF_HEADS_UP_MINUTES: 0,
        }
    )
    with route_patch(30):
        await _setup(hass, entry)
        assert not lights  # not time yet

        await _advance(hass, freezer, minutes=10, seconds=5)
        assert len(lights) == 1
        assert lights[0].data["rgb_color"] == [0, 255, 0]
        assert lights[0].data["flash"] == "long"
        assert len(tts) == 1
        assert "Dentist" in tts[0].data["message"]
        assert "30 minutes" in tts[0].data["message"]
        assert len(notify) == 1
        assert len(fired) == 1 and fired[0].data["tier"] == "leave_now"
        assert _state(hass, "_time_to_leave").state == "on"

        # Later refreshes must not re-fire.
        coordinator = entry.runtime_data
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert len(lights) == 1


async def test_heads_up_and_leave_now_are_separate_alerts(hass: HomeAssistant, freezer) -> None:
    lights = async_mock_service(hass, "light", "turn_on")
    # Leave in 40 min; heads-up 30 min before -> due in 10 min.
    await register_calendar(hass, [make_event(75)])
    entry = _entry(**{CONF_LIGHTS: ["light.hall"], CONF_HEADS_UP_MINUTES: 30})
    with route_patch(30):
        await _setup(hass, entry)
        await _advance(hass, freezer, minutes=10, seconds=5)
        assert [c.data["rgb_color"] for c in lights] == [[255, 170, 0]]
        await _advance(hass, freezer, minutes=30)
        assert [c.data["rgb_color"] for c in lights] == [[255, 170, 0], [0, 255, 0]]


async def test_restart_does_not_refire_alerts(hass: HomeAssistant, hass_storage) -> None:
    lights = async_mock_service(hass, "light", "turn_on")
    # Leave-by was 2 minutes ago: alert fires on first setup...
    await register_calendar(hass, [make_event(33)])
    entry = _entry(**{CONF_LIGHTS: ["light.hall"], CONF_HEADS_UP_MINUTES: 0})
    with route_patch(30):
        await _setup(hass, entry)
        assert len(lights) == 1
        # ...but not again after the integration is reloaded (a "restart").
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert len(lights) == 1


async def test_stale_alert_is_skipped_not_fired(hass: HomeAssistant) -> None:
    """If we only learn about the event 30 min after leave-by, stay quiet."""
    lights = async_mock_service(hass, "light", "turn_on")
    await register_calendar(hass, [make_event(50)])
    entry = _entry(**{CONF_LIGHTS: ["light.hall"], CONF_HEADS_UP_MINUTES: 0})
    with route_patch(80):  # leave-by = 50 - 80 - 5 = 35 min ago > 15 min grace
        await _setup(hass, entry)
    assert not lights


async def test_dismiss_skips_event(hass: HomeAssistant) -> None:
    await register_calendar(hass, [make_event(60, "First", uid="a"), make_event(180, "Second", uid="b")])
    entry = _entry()
    with route_patch(10):
        await _setup(hass, entry)
        assert _state(hass, "_next_event").state == "First"
        assert await entry.runtime_data.async_dismiss_current()
        await hass.async_block_till_done()
    assert _state(hass, "_next_event").state == "Second"


async def test_failing_light_does_not_block_speech(hass: HomeAssistant) -> None:
    from homeassistant.exceptions import HomeAssistantError

    async def boom(call):
        raise HomeAssistantError("light offline")

    hass.services.async_register("light", "turn_on", boom)
    tts = async_mock_service(hass, "tts", "speak")
    await register_calendar(hass, [make_event(33)])
    entry = _entry(
        **{
            CONF_LIGHTS: ["light.hall"],
            CONF_SPEAKERS: ["media_player.kitchen"],
            CONF_TTS_ENTITY: "tts.test",
            CONF_HEADS_UP_MINUTES: 0,
        }
    )
    with route_patch(30):
        await _setup(hass, entry)
    assert len(tts) == 1


async def test_mirror_helpers(hass: HomeAssistant) -> None:
    started = async_mock_service(hass, "timer", "start")
    texts = async_mock_service(hass, "input_text", "set_value")
    hass.states.async_set("timer.leave_by_countdown", "idle")
    hass.states.async_set("input_text.leave_by_event", "", {"max": 100})
    await register_calendar(hass, [make_event(90, "Choir practice")])
    entry = _entry(
        timer_entity="timer.leave_by_countdown", text_entity="input_text.leave_by_event"
    )
    with route_patch(20):
        await _setup(hass, entry)
    assert len(started) == 1
    assert 64 * 60 <= started[0].data["duration"] <= 65 * 60
    assert texts[0].data["value"] == "Choir practice"


async def test_event_tag_switches_that_event_to_transit(hass: HomeAssistant) -> None:
    """A #transit tag changes only that event's mode, and timetable departure wins."""
    from unittest.mock import patch

    from custom_components.leave_by.api import RouteResult

    await register_calendar(
        hass,
        [
            make_event(120, "Choir #transit", "Church", "t1"),
            make_event(240, "Dentist", "Clinic", "d1"),
        ],
    )
    start = dt_util.utcnow() + timedelta(minutes=120)
    # Bus boards (and we must set off) 50 minutes before the event.
    transit = RouteResult(1800, 1800, depart_at=start - timedelta(minutes=50))
    drive = RouteResult(900, 900)

    async def fake(self, origin, destination, *, mode="DRIVE", **kw):
        return transit if mode == "TRANSIT" else drive

    with patch("custom_components.leave_by.coordinator.RoutesClient.compute", fake):
        await _setup(hass, _entry(**{CONF_BUFFER_MINUTES: 5}))

    # Transit event: leave_by = set-off time (T-50) - 5 min buffer = T-55 -> ~65 min away.
    remaining = int(_state(hass, "_seconds_remaining").state)
    assert 64 * 60 <= remaining <= 65 * 60
    assert _state(hass, "_next_event").attributes["travel_mode"] == "TRANSIT"
    assert _state(hass, "_travel_time").state == "50.0"


async def test_bad_key_starts_reauth_and_new_key_recovers(hass: HomeAssistant) -> None:
    from unittest.mock import patch

    from custom_components.leave_by.api import RouteResult, RoutesInvalidKey

    await register_calendar(hass, [make_event(90)])
    entry = _entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.leave_by.coordinator.RoutesClient.compute",
        side_effect=RoutesInvalidKey("revoked"),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flows and flows[0]["context"]["source"] == "reauth"

    with patch(
        "custom_components.leave_by.config_flow.RoutesClient.compute",
        return_value=RouteResult(600, 600),
    ), route_patch(20):
        result = await hass.config_entries.flow.async_configure(
            flows[0]["flow_id"], {"api_key": "new-key"}
        )
        await hass.async_block_till_done()
    assert result["type"] == "abort" and result["reason"] == "reauth_successful"
    assert entry.data["api_key"] == "new-key"
    assert entry.state is ConfigEntryState.LOADED
