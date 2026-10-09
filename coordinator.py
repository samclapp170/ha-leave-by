"""Data coordinator for Leave By."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .alerts import async_dispatch_alert
from .api import (
    RoutesApiDisabled,
    RoutesClient,
    RoutesConnectionError,
    RoutesError,
    RoutesInvalidKey,
    RoutesNoRoute,
    RoutesPermissionDenied,
    place_address,
    place_latlng,
)
from .const import (
    CONF_API_KEY,
    CONF_BUFFER_MINUTES,
    CONF_CALENDARS,
    CONF_COUNTDOWN_TYPE,
    CONF_EVENT_TAGS,
    CONF_HEADS_UP_MINUTES,
    CONF_LATE_MINUTES,
    CONF_LIVE_TRAFFIC,
    CONF_LOOKAHEAD_HOURS,
    CONF_ORIGIN_ADDRESS,
    CONF_ORIGIN_ENTITY,
    CONF_ORIGIN_TYPE,
    CONF_POLL_MINUTES,
    CONF_TEXT_ENTITY,
    CONF_TIMER_ENTITY,
    CONF_TRAVEL_MODE,
    COUNTDOWN_EVENT_START,
    DEFAULTS,
    DOMAIN,
    MODE_DRIVE,
    MODE_TRANSIT,
    ORIGIN_ADDRESS,
    ORIGIN_TRACKER,
    TIER_LEAVE_NOW,
    TIERS,
    TRAVEL_CACHE_SECONDS,
    TRAVEL_STALE_MAX_SECONDS,
)
from .logic import (
    classify_alert,
    compute_leave_by,
    event_key,
    is_virtual_location,
    parse_mode_tag,
    seconds_until,
    tier_time,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
FIRED_RETENTION = timedelta(days=2)

type LeaveByConfigEntry = ConfigEntry[LeaveByCoordinator]


@dataclass
class TripEvent:
    """A calendar event with a computed travel estimate."""

    key: str
    summary: str
    location: str
    calendar: str
    start: datetime
    mode: str = MODE_DRIVE
    depart_at: datetime | None = None  # transit: when to set off for the boarding time
    travel_seconds: int | None = None
    static_seconds: int | None = None
    leave_by: datetime | None = None
    fetched_at: datetime | None = None


@dataclass
class LeaveByData:
    """Everything the entities need."""

    events: list[TripEvent] = field(default_factory=list)  # sorted by leave_by
    origin_label: str = ""
    skipped: list[str] = field(default_factory=list)
    updated: datetime | None = None

    def current(self, now: datetime, dismissed: set[str] | None = None) -> TripEvent | None:
        """The event the countdown should show right now."""
        for ev in self.events:
            if ev.start > now and ev.leave_by and ev.key not in (dismissed or set()):
                return ev
        return None

    def upcoming(self, now: datetime, dismissed: set[str] | None = None) -> list[TripEvent]:
        return [
            ev
            for ev in self.events
            if ev.start > now and ev.key not in (dismissed or set())
        ]


class LeaveByCoordinator(DataUpdateCoordinator[LeaveByData]):
    """Polls calendars + Google Routes and fires alerts on schedule."""

    config_entry: LeaveByConfigEntry

    def __init__(self, hass: HomeAssistant, entry: LeaveByConfigEntry) -> None:
        self.cfg: dict[str, Any] = {**DEFAULTS, **entry.data, **entry.options}
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(minutes=int(self.cfg[CONF_POLL_MINUTES])),
        )
        self._client = RoutesClient(async_get_clientsession(hass), self.cfg[CONF_API_KEY])
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._fired: dict[str, str] = {}
        self.dismissed: set[str] = set()
        # event key -> (duration, static, fetched_at, origin signature)
        self._travel_cache: dict[str, tuple[int, int, datetime, str]] = {}
        self._wake_unsub: CALLBACK_TYPE | None = None
        self._warned: set[str] = set()

    # ------------------------------------------------------------------ setup
    async def async_load(self) -> None:
        """Load persisted alert state (so restarts never double-fire)."""
        stored = await self._store.async_load() or {}
        self._fired = dict(stored.get("fired", {}))
        self.dismissed = set(stored.get("dismissed", []))

    async def _async_save(self) -> None:
        cutoff = dt_util.utcnow() - FIRED_RETENTION
        self._fired = {
            k: v
            for k, v in self._fired.items()
            if (dt_util.parse_datetime(v) or cutoff) >= cutoff
        }
        await self._store.async_save(
            {"fired": self._fired, "dismissed": sorted(self.dismissed)}
        )

    @callback
    def async_shutdown_listeners(self) -> None:
        if self._wake_unsub:
            self._wake_unsub()
            self._wake_unsub = None

    async def async_shutdown(self) -> None:
        self.async_shutdown_listeners()
        await super().async_shutdown()

    # ------------------------------------------------------------------ origin
    def _origin(self) -> tuple[dict[str, Any], str]:
        """Return (routes waypoint, signature) for where the trip starts."""
        cfg = self.cfg
        home = (self.hass.config.latitude, self.hass.config.longitude)
        otype = cfg[CONF_ORIGIN_TYPE]
        if otype == ORIGIN_ADDRESS and cfg.get(CONF_ORIGIN_ADDRESS):
            addr = cfg[CONF_ORIGIN_ADDRESS]
            return place_address(addr), f"addr:{addr}"
        if otype == ORIGIN_TRACKER and cfg.get(CONF_ORIGIN_ENTITY):
            state = self.hass.states.get(cfg[CONF_ORIGIN_ENTITY])
            lat = state.attributes.get("latitude") if state else None
            lon = state.attributes.get("longitude") if state else None
            if lat is not None and lon is not None:
                return place_latlng(lat, lon), f"ll:{round(lat, 3)},{round(lon, 3)}"
            _LOGGER.debug("Origin tracker has no location; falling back to home")
        return place_latlng(*home), f"ll:{round(home[0], 3)},{round(home[1], 3)}"

    # --------------------------------------------------------------- calendars
    async def _fetch_events(self, now: datetime) -> list[TripEvent]:
        horizon = now + timedelta(hours=float(self.cfg[CONF_LOOKAHEAD_HOURS]))
        found: dict[str, TripEvent] = {}
        failures = 0
        calendars: list[str] = self.cfg[CONF_CALENDARS]
        for entity_id in calendars:
            try:
                response = await self.hass.services.async_call(
                    "calendar",
                    "get_events",
                    {
                        "entity_id": entity_id,
                        "start_date_time": now.isoformat(),
                        "end_date_time": horizon.isoformat(),
                    },
                    blocking=True,
                    return_response=True,
                )
            except HomeAssistantError as err:
                failures += 1
                _LOGGER.warning("Could not read calendar %s: %s", entity_id, err)
                continue
            for raw in (response or {}).get(entity_id, {}).get("events", []):
                ev = self._parse_event(entity_id, raw, now, horizon)
                if ev:
                    found[ev.key] = ev
        if calendars and failures == len(calendars):
            raise UpdateFailed("None of the selected calendars could be read")
        return list(found.values())

    def _parse_event(
        self, calendar: str, raw: dict[str, Any], now: datetime, horizon: datetime
    ) -> TripEvent | None:
        start_raw = str(raw.get("start", ""))
        if "T" not in start_raw:
            return None  # all-day events have no time to count down to
        start = dt_util.parse_datetime(start_raw)
        if start is None:
            return None
        start = dt_util.as_utc(start)
        if start <= now or start > horizon:
            return None
        location = (raw.get("location") or "").strip()
        summary = raw.get("summary") or "Event"
        if is_virtual_location(location):
            return None
        mode = self.cfg[CONF_TRAVEL_MODE]
        if self.cfg[CONF_EVENT_TAGS]:
            mode = parse_mode_tag(summary, raw.get("description")) or mode
        return TripEvent(
            key=event_key(calendar, raw.get("uid"), summary, start),
            summary=summary,
            location=location,
            calendar=calendar,
            start=start,
            mode=mode,
        )

    # ------------------------------------------------------------ travel times
    async def _estimate(
        self,
        ev: TripEvent,
        origin: dict[str, Any],
        signature: str,
        now: datetime,
    ) -> None:
        """Fill in travel/leave-by on an event (cache, API, or stale fallback)."""
        cfg = self.cfg
        buffer_min = float(cfg[CONF_BUFFER_MINUTES])
        cache_key = ev.key
        cached = self._travel_cache.get(cache_key)

        if (
            cached
            and cached[3] == signature
            and (now - cached[2]).total_seconds() < TRAVEL_CACHE_SECONDS
        ):
            duration, static, fetched, _ = cached
        else:
            # Predict traffic for the time we'll actually be on the road.
            departure = now + timedelta(seconds=15)
            if cached and ev.mode == MODE_DRIVE:
                predicted = ev.start - timedelta(seconds=cached[0], minutes=buffer_min)
                departure = max(departure, predicted)
            try:
                result = await self._client.compute(
                    origin,
                    place_address(ev.location),
                    mode=ev.mode,
                    traffic=bool(cfg[CONF_LIVE_TRAFFIC]),
                    departure=departure,
                    arrival=ev.start if ev.mode == MODE_TRANSIT else None,
                )
            except (RoutesInvalidKey, RoutesApiDisabled, RoutesPermissionDenied) as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except RoutesNoRoute as err:
                if ev.key not in self._warned:
                    self._warned.add(ev.key)
                    _LOGGER.warning(
                        "No route to '%s' for event '%s': %s", ev.location, ev.summary, err
                    )
                if not cached:
                    return
                duration, static, fetched, _ = cached
            except (RoutesConnectionError, RoutesError) as err:
                _LOGGER.warning("Travel time lookup failed for '%s': %s", ev.summary, err)
                if not cached or (now - cached[2]).total_seconds() > TRAVEL_STALE_MAX_SECONDS:
                    return
                duration, static, fetched, _ = cached
            else:
                duration, static, fetched = result.duration, result.static_duration, now
                if ev.mode == MODE_TRANSIT and result.depart_at:
                    # Timetable-aware: count the wait for the vehicle as travel,
                    # so "leave by" lands on the moment to head for the stop.
                    ev.depart_at = result.depart_at
                    duration = max(int((ev.start - result.depart_at).total_seconds()), 0)
                self._travel_cache[cache_key] = (duration, static, fetched, signature)

        ev.travel_seconds = duration
        ev.static_seconds = static
        ev.fetched_at = fetched
        ev.leave_by = compute_leave_by(ev.start, duration, buffer_min)

    # ------------------------------------------------------------------ update
    async def _async_update_data(self) -> LeaveByData:
        now = dt_util.utcnow()
        origin, signature = self._origin()
        events = await self._fetch_events(now)

        skipped: list[str] = []
        for ev in events:
            await self._estimate(ev, origin, signature, now)
            if ev.leave_by is None:
                skipped.append(ev.summary)

        # Forget cache entries for events that dropped out of the window.
        live = {e.key for e in events}
        self._travel_cache = {k: v for k, v in self._travel_cache.items() if k in live}

        ready = sorted((e for e in events if e.leave_by), key=lambda e: e.leave_by)
        data = LeaveByData(
            events=ready,
            origin_label=signature,
            skipped=skipped,
            updated=now,
        )
        self.data = data  # make visible to helpers before listeners run
        await self._async_evaluate_alerts(data, now)
        await self._async_mirror_helpers(data, now)
        self._schedule_wake(data, now)
        return data

    # ------------------------------------------------------------------ alerts
    def _tier_due(self, ev: TripEvent, tier: str) -> datetime | None:
        assert ev.leave_by is not None
        return tier_time(
            ev.leave_by,
            tier,
            int(self.cfg[CONF_HEADS_UP_MINUTES]),
            int(self.cfg[CONF_LATE_MINUTES]),
        )

    async def _async_evaluate_alerts(self, data: LeaveByData, now: datetime) -> None:
        changed = False
        for ev in data.upcoming(now, self.dismissed):
            if ev.leave_by is None:
                continue
            for tier in TIERS:
                due = self._tier_due(ev, tier)
                if due is None:
                    continue
                fkey = f"{ev.key}|{tier}"
                if fkey in self._fired:
                    continue
                verdict = classify_alert(now, due, ev.start)
                if verdict == "wait":
                    continue
                self._fired[fkey] = now.isoformat()
                changed = True
                if verdict == "fire":
                    _LOGGER.debug("Firing %s alert for %s", tier, ev.summary)
                    self.hass.async_create_task(
                        async_dispatch_alert(self.hass, self.cfg, tier, ev, now),
                        name=f"leave_by alert {tier}",
                    )
        if changed:
            await self._async_save()

    @callback
    def _schedule_wake(self, data: LeaveByData, now: datetime) -> None:
        """Wake exactly when the next alert is due or the current event starts."""
        self.async_shutdown_listeners()
        moments: list[datetime] = []
        for ev in data.upcoming(now, self.dismissed):
            if ev.leave_by is None:
                continue
            moments.append(ev.start)
            for tier in TIERS:
                due = self._tier_due(ev, tier)
                if due and due > now and f"{ev.key}|{tier}" not in self._fired:
                    moments.append(due)
        future = [m for m in moments if m > now]
        if not future:
            return
        target = min(future) + timedelta(seconds=1)
        self._wake_unsub = async_track_point_in_utc_time(
            self.hass, self._handle_wake, target
        )

    async def _handle_wake(self, _now: datetime) -> None:
        self._wake_unsub = None
        await self.async_refresh()

    # ------------------------------------------------------- manual operations
    async def async_test_alert(self, tier: str = TIER_LEAVE_NOW) -> None:
        """Run the alert actions against a made-up event."""
        now = dt_util.utcnow()
        travel = 20 * 60
        buffer_min = float(self.cfg[CONF_BUFFER_MINUTES])
        start = now + timedelta(seconds=travel) + timedelta(minutes=buffer_min)
        event = TripEvent(
            key="test",
            summary="Test event",
            location="Test location",
            calendar="calendar.test",
            start=start,
            travel_seconds=travel,
            static_seconds=travel,
            leave_by=compute_leave_by(start, travel, buffer_min),
        )
        await async_dispatch_alert(self.hass, self.cfg, tier, event, now)

    async def async_dismiss_current(self) -> bool:
        """Skip the current event (e.g. "I'm already in the car")."""
        now = dt_util.utcnow()
        ev = self.data.current(now, self.dismissed) if self.data else None
        if ev is None:
            return False
        self.dismissed.add(ev.key)
        await self._async_save()
        await self.async_refresh()
        return True

    # ------------------------------------------------------- dashboard helpers
    def target_time(self, ev: TripEvent) -> datetime | None:
        if self.cfg[CONF_COUNTDOWN_TYPE] == COUNTDOWN_EVENT_START:
            return ev.start
        return ev.leave_by

    async def _async_mirror_helpers(self, data: LeaveByData, now: datetime) -> None:
        """Optionally drive a timer helper / input_text (for timer-based cards)."""
        timer_id = self.cfg.get(CONF_TIMER_ENTITY)
        text_id = self.cfg.get(CONF_TEXT_ENTITY)
        if not timer_id and not text_id:
            return
        ev = data.current(now, self.dismissed)
        target = self.target_time(ev) if ev else None
        remaining = seconds_until(target, now) if target else 0

        if timer_id:
            try:
                await self._mirror_timer(timer_id, target, remaining, now)
            except HomeAssistantError as err:
                _LOGGER.warning("Could not update timer %s: %s", timer_id, err)
        if text_id:
            try:
                await self._mirror_text(text_id, ev.summary if ev else "")
            except HomeAssistantError as err:
                _LOGGER.warning("Could not update %s: %s", text_id, err)

    async def _mirror_timer(
        self, timer_id: str, target: datetime | None, remaining: int, now: datetime
    ) -> None:
        state = self.hass.states.get(timer_id)
        if state is None:
            return
        if target is None or remaining <= 0:
            if state.state != "idle":
                await self.hass.services.async_call(
                    "timer", "cancel", {"entity_id": timer_id}, blocking=True
                )
            return
        if state.state == "active":
            finishes = dt_util.parse_datetime(str(state.attributes.get("finishes_at", "")))
            if finishes and abs((finishes - target).total_seconds()) < 5:
                return
        await self.hass.services.async_call(
            "timer",
            "start",
            {"entity_id": timer_id, "duration": remaining},
            blocking=True,
        )

    async def _mirror_text(self, text_id: str, value: str) -> None:
        state = self.hass.states.get(text_id)
        if state is None:
            return
        max_len = int(state.attributes.get("max", 100))
        value = value[:max_len]
        if state.state != value:
            await self.hass.services.async_call(
                "input_text",
                "set_value",
                {"entity_id": text_id, "value": value},
                blocking=True,
            )
