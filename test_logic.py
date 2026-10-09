"""Tests for the pure helper logic."""

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.leave_by.logic import (
    classify_alert,
    compute_leave_by,
    format_countdown,
    is_virtual_location,
    render_message,
    round_minutes,
    seconds_until,
    tier_time,
)

UTC = timezone.utc
T0 = datetime(2026, 10, 7, 18, 0, tzinfo=UTC)


def test_leave_by_includes_travel_and_car_buffer():
    # 6:00pm event, 25 min drive, 5 min to get to the car -> leave at 5:30pm
    assert compute_leave_by(T0, 25 * 60, 5) == T0 - timedelta(minutes=30)


def test_zero_buffer():
    assert compute_leave_by(T0, 600, 0) == T0 - timedelta(minutes=10)


@pytest.mark.parametrize(
    ("seconds", "style", "expected"),
    [
        (3909, "clock", "1:05:09"),
        (2530, "clock", "42:10"),
        (59, "clock", "00:59"),
        (0, "clock", "00:00"),
        (-192, "clock", "-03:12"),
        (3909, "friendly", "1h 05m"),
        (2530, "friendly", "42m"),
        (45, "friendly", "45s"),
        (-192, "friendly", "Late 3m"),
        (None, "clock", None),
    ],
)
def test_format_countdown(seconds, style, expected):
    assert format_countdown(seconds, style) == expected


def test_seconds_until_floors_and_goes_negative():
    assert seconds_until(T0, T0 - timedelta(seconds=90, milliseconds=500)) == 90
    assert seconds_until(T0, T0 + timedelta(seconds=10)) == -10


@pytest.mark.parametrize(
    ("location", "virtual"),
    [
        (None, True),
        ("", True),
        ("   ", True),
        ("https://zoom.us/j/123", True),
        ("meet.google.com/abc-defg", True),
        ("Microsoft Teams meeting teams.microsoft.com/l/x", True),
        ("123 Peachtree St NE, Atlanta, GA", False),
        ("Oakhurst Baptist Church", False),
    ],
)
def test_is_virtual_location(location, virtual):
    assert is_virtual_location(location) is virtual


def test_tier_times_and_disabled_tiers():
    leave = T0
    assert tier_time(leave, "heads_up", 30, 0) == T0 - timedelta(minutes=30)
    assert tier_time(leave, "heads_up", 0, 0) is None
    assert tier_time(leave, "leave_now", 30, 0) == T0
    assert tier_time(leave, "late", 30, 0) is None
    assert tier_time(leave, "late", 30, 5) == T0 + timedelta(minutes=5)


def test_classify_alert_windows():
    start = T0 + timedelta(minutes=40)
    due = T0
    assert classify_alert(T0 - timedelta(seconds=1), due, start) == "wait"
    assert classify_alert(T0, due, start) == "fire"
    assert classify_alert(T0 + timedelta(minutes=14), due, start) == "fire"
    # HA was down: alert is stale, skip silently rather than announce late
    assert classify_alert(T0 + timedelta(minutes=16), due, start) == "skip"
    # never alert for an event that already started
    assert classify_alert(start, due, start) == "skip"


def test_render_message_fills_known_and_keeps_unknown():
    out = render_message("Go to {event} in {minutes} min {nope}", {"event": "Dentist", "minutes": 5})
    assert out == "Go to Dentist in 5 min {nope}"


def test_render_message_survives_bad_template():
    assert render_message("broken {", {"event": "x"}) == "broken {"


def test_round_minutes():
    assert round_minutes(0) == 0
    assert round_minutes(89) == 1
    assert round_minutes(91) == 2
    assert round_minutes(-50) == 0


@pytest.mark.parametrize(
    ("texts", "mode"),
    [
        (("Dentist #transit",), "TRANSIT"),
        (("Dentist", "Take the #Bus this time"), "TRANSIT"),
        (("Lunch #walk",), "WALK"),
        (("Ride #bike",), "BICYCLE"),
        (("Airport run #car",), "DRIVE"),
        (("Meeting #unknowntag",), None),
        (("Dad&#39;s birthday",), None),  # HTML entity, not a tag
        (("Issue #42",), None),
        (("Plain event", None, ""), None),
        (("#train and #walk",), "TRANSIT"),  # first recognised tag wins
    ],
)
def test_parse_mode_tag(texts, mode):
    from custom_components.leave_by.logic import parse_mode_tag

    assert parse_mode_tag(*texts) == mode
