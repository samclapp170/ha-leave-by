"""Minimal async client for the Google Routes API (computeRoutes)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from .const import MODE_DRIVE, MODE_TRANSIT

_LOGGER = logging.getLogger(__name__)

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = "routes.duration,routes.staticDuration"
# Transit also needs the steps, to find when the first vehicle boards.
TRANSIT_FIELD_MASK = (
    "routes.duration,routes.staticDuration,"
    "routes.legs.steps.staticDuration,"
    "routes.legs.steps.transitDetails.stopDetails.departureTime"
)


class RoutesError(Exception):
    """Base error for the Routes API client."""


class RoutesConnectionError(RoutesError):
    """Could not reach Google."""


class RoutesInvalidKey(RoutesError):
    """The API key is not valid."""


class RoutesApiDisabled(RoutesError):
    """The Routes API is not enabled for the key's project."""


class RoutesPermissionDenied(RoutesError):
    """Key restricted, billing disabled, or otherwise forbidden."""


class RoutesQuotaExceeded(RoutesError):
    """Quota or rate limit hit."""


class RoutesNoRoute(RoutesError):
    """Address could not be resolved or no route exists."""


@dataclass(frozen=True)
class RouteResult:
    """Result of a route lookup, in seconds."""

    duration: int  # with live/predicted traffic when requested
    static_duration: int  # without traffic
    # Transit only: when you must leave the origin to catch the first vehicle
    # (boarding time minus the walk to the stop), for a trip arriving on time.
    depart_at: datetime | None = None


def place_latlng(latitude: float, longitude: float) -> dict[str, Any]:
    """Build a Routes API waypoint from coordinates."""
    return {
        "location": {"latLng": {"latitude": latitude, "longitude": longitude}}
    }


def place_address(address: str) -> dict[str, Any]:
    """Build a Routes API waypoint from a free-text address."""
    return {"address": address}


def _parse_seconds(value: str | None) -> int:
    # The API returns durations like "1234s" (sometimes "1234.5s").
    if not value:
        raise RoutesNoRoute("No duration in response")
    return int(round(float(value.rstrip("s"))))


def _transit_departure(route: dict[str, Any]) -> datetime | None:
    """Time you must set off to board the first transit vehicle.

    = boarding time of the first transit step - duration of the steps before it
    (the walk to the stop). Returns None if the route has no transit step.
    """
    walk_seconds = 0
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            boarding = (
                step.get("transitDetails", {}).get("stopDetails", {}).get("departureTime")
            )
            if boarding:
                try:
                    boards = datetime.fromisoformat(boarding)
                except ValueError:
                    return None
                return boards - timedelta(seconds=walk_seconds)
            if step.get("staticDuration"):
                walk_seconds += _parse_seconds(step["staticDuration"])
    return None


def _error_info(payload: Any) -> tuple[str, str, set[str]]:
    """Pull (status, message, reasons) out of a Google error body."""
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    reasons = {
        d.get("reason", "")
        for d in error.get("details", [])
        if isinstance(d, dict) and d.get("reason")
    }
    return error.get("status", ""), error.get("message", ""), reasons


class RoutesClient:
    """Tiny wrapper around computeRoutes."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = api_key

    async def compute(
        self,
        origin: dict[str, Any],
        destination: dict[str, Any],
        *,
        mode: str = MODE_DRIVE,
        traffic: bool = True,
        departure: datetime | None = None,
        arrival: datetime | None = None,
    ) -> RouteResult:
        """Return travel time between two waypoints.

        For transit, pass ``arrival`` (the event start) to get a timetable-aware
        trip that gets you there on time.
        """
        body: dict[str, Any] = {
            "origin": origin,
            "destination": destination,
            "travelMode": mode,
        }
        if mode == MODE_DRIVE and traffic:
            body["routingPreference"] = "TRAFFIC_AWARE"
        if mode == MODE_TRANSIT and arrival is not None:
            body["arrivalTime"] = arrival.strftime("%Y-%m-%dT%H:%M:%SZ")
        elif departure is not None and (
            (mode == MODE_DRIVE and traffic) or mode == MODE_TRANSIT
        ):
            body["departureTime"] = departure.strftime("%Y-%m-%dT%H:%M:%SZ")

        headers = {
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": TRANSIT_FIELD_MASK if mode == MODE_TRANSIT else FIELD_MASK,
            "Content-Type": "application/json",
        }
        try:
            async with asyncio.timeout(20):
                resp = await self._session.post(ROUTES_URL, json=body, headers=headers)
                try:
                    payload = await resp.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError):
                    payload = {}
                status_code = resp.status
        except (TimeoutError, aiohttp.ClientError) as err:
            raise RoutesConnectionError(str(err)) from err

        if status_code == 200:
            routes = payload.get("routes") if isinstance(payload, dict) else None
            if not routes:
                raise RoutesNoRoute("No route found")
            route = routes[0]
            duration = _parse_seconds(route.get("duration"))
            static = (
                _parse_seconds(route["staticDuration"])
                if route.get("staticDuration")
                else duration
            )
            depart_at = _transit_departure(route) if mode == MODE_TRANSIT else None
            return RouteResult(
                duration=duration, static_duration=static, depart_at=depart_at
            )

        status, message, reasons = _error_info(payload)
        _LOGGER.debug("Routes API error %s %s: %s", status_code, status, message)

        if "API_KEY_INVALID" in reasons or "API key not valid" in message:
            raise RoutesInvalidKey(message)
        if "SERVICE_DISABLED" in reasons or "has not been used" in message:
            raise RoutesApiDisabled(message)
        if status_code in (401, 403):
            raise RoutesPermissionDenied(message or f"HTTP {status_code}")
        if status_code == 429 or status == "RESOURCE_EXHAUSTED":
            raise RoutesQuotaExceeded(message)
        if status_code in (400, 404):
            raise RoutesNoRoute(message or f"HTTP {status_code}")
        raise RoutesError(message or f"HTTP {status_code}")
