"""Routes API client parsing and error mapping."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.leave_by.api import (
    ROUTES_URL,
    RoutesApiDisabled,
    RoutesClient,
    RoutesInvalidKey,
    RoutesNoRoute,
    RoutesPermissionDenied,
    RoutesQuotaExceeded,
    place_address,
    place_latlng,
)

ORIGIN = place_latlng(33.7, -84.3)
DEST = place_address("1 Main St")


async def _client(hass):
    return RoutesClient(async_get_clientsession(hass), "KEY")


async def test_drive_request_and_parse(hass, aioclient_mock):
    aioclient_mock.post(
        ROUTES_URL, json={"routes": [{"duration": "1500s", "staticDuration": "1200s"}]}
    )
    client = await _client(hass)
    dep = datetime(2026, 10, 8, 12, 0, 5, tzinfo=timezone.utc)
    result = await client.compute(ORIGIN, DEST, mode="DRIVE", traffic=True, departure=dep)
    assert (result.duration, result.static_duration) == (1500, 1200)

    _, _, body, headers = aioclient_mock.mock_calls[0]
    assert body["routingPreference"] == "TRAFFIC_AWARE"
    assert body["departureTime"] == "2026-10-08T12:00:05Z"
    assert body["travelMode"] == "DRIVE"
    assert headers["X-Goog-Api-Key"] == "KEY"
    assert headers["X-Goog-FieldMask"] == "routes.duration,routes.staticDuration"


async def test_walk_sends_no_traffic_fields(hass, aioclient_mock):
    aioclient_mock.post(ROUTES_URL, json={"routes": [{"duration": "600s"}]})
    client = await _client(hass)
    dep = datetime(2026, 10, 8, 12, 0, 5, tzinfo=timezone.utc)
    result = await client.compute(ORIGIN, DEST, mode="WALK", traffic=True, departure=dep)
    assert result.duration == 600 and result.static_duration == 600
    body = aioclient_mock.mock_calls[0][2]
    assert "routingPreference" not in body and "departureTime" not in body


async def test_transit_uses_arrival_time_and_finds_boarding(hass, aioclient_mock):
    """Walk 6 min to the stop, bus boards 17:40 -> must set off at 17:34."""
    aioclient_mock.post(
        ROUTES_URL,
        json={
            "routes": [
                {
                    "duration": "2400s",
                    "staticDuration": "2400s",
                    "legs": [
                        {
                            "steps": [
                                {"staticDuration": "360s"},
                                {
                                    "staticDuration": "1500s",
                                    "transitDetails": {
                                        "stopDetails": {"departureTime": "2026-10-08T17:40:00Z"}
                                    },
                                },
                                {"staticDuration": "300s"},
                            ]
                        }
                    ],
                }
            ]
        },
    )
    client = await _client(hass)
    start = datetime(2026, 10, 8, 18, 15, tzinfo=timezone.utc)
    result = await client.compute(ORIGIN, DEST, mode="TRANSIT", traffic=True, arrival=start)
    assert result.depart_at == datetime(2026, 10, 8, 17, 34, tzinfo=timezone.utc)

    _, _, body, headers = aioclient_mock.mock_calls[0]
    assert body["arrivalTime"] == "2026-10-08T18:15:00Z"
    assert "departureTime" not in body and "routingPreference" not in body
    assert "transitDetails" in headers["X-Goog-FieldMask"]


@pytest.mark.parametrize(
    ("status", "payload", "exc"),
    [
        (400, {"error": {"status": "INVALID_ARGUMENT", "message": "API key not valid. Please pass a valid API key.", "details": [{"reason": "API_KEY_INVALID"}]}}, RoutesInvalidKey),
        (403, {"error": {"status": "PERMISSION_DENIED", "message": "Routes API has not been used in project 1 before or it is disabled.", "details": [{"reason": "SERVICE_DISABLED"}]}}, RoutesApiDisabled),
        (403, {"error": {"status": "PERMISSION_DENIED", "message": "Requests from referer <empty> are blocked.", "details": [{"reason": "API_KEY_HTTP_REFERRER_BLOCKED"}]}}, RoutesPermissionDenied),
        (429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota"}}, RoutesQuotaExceeded),
        (404, {"error": {"status": "NOT_FOUND", "message": "address not found"}}, RoutesNoRoute),
        (200, {}, RoutesNoRoute),
    ],
)
async def test_error_mapping(hass, aioclient_mock, status, payload, exc):
    aioclient_mock.post(ROUTES_URL, status=status, text=json.dumps(payload))
    client = await _client(hass)
    with pytest.raises(exc):
        await client.compute(ORIGIN, DEST)
