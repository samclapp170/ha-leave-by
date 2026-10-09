"""Pure helper logic for Leave By (no Home Assistant imports, easy to test)."""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from typing import Any

from .const import (
    ALERT_GRACE_SECONDS,
    MODE_TAGS,
    STYLE_CLOCK,
    TIER_HEADS_UP,
    TIER_LATE,
    TIER_LEAVE_NOW,
)

_VIRTUAL_PATTERN = re.compile(
    r"^(https?://|www\.)|zoom\.us|meet\.google\.com|teams\.microsoft\.com|"
    r"webex\.com|gotomeeting\.com|whereby\.com",
    re.IGNORECASE,
)


def is_virtual_location(location: str | None) -> bool:
    """Return True if the location is empty or just a video-call link."""
    if not location or not location.strip():
        return True
    return bool(_VIRTUAL_PATTERN.search(location.strip()))


def compute_leave_by(
    start: datetime, travel_seconds: float, buffer_minutes: float
) -> datetime:
    """Moment to start heading out: event start - travel time - buffer."""
    return start - timedelta(seconds=travel_seconds) - timedelta(minutes=buffer_minutes)


def seconds_until(target: datetime, now: datetime) -> int:
    """Whole seconds from now until target (negative once passed)."""
    return math.floor((target - now).total_seconds())


def format_countdown(seconds: int | None, style: str = STYLE_CLOCK) -> str | None:
    """Format a number of seconds as text.

    clock:    "1:05:09", "42:10", "-03:12" (negative = running late)
    friendly: "1h 05m", "42m", "45s", "Late 3m"
    """
    if seconds is None:
        return None
    late = seconds < 0
    total = abs(int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if style == STYLE_CLOCK:
        text = f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"
        return f"-{text}" if late else text
    if hours:
        text = f"{hours}h {minutes:02d}m"
    elif minutes:
        text = f"{minutes}m"
    else:
        text = f"{secs}s"
    return f"Late {text}" if late else text


def tier_time(
    leave_by: datetime, tier: str, heads_up_minutes: int, late_minutes: int
) -> datetime | None:
    """When a tier is due for an event, or None if that tier is disabled."""
    if tier == TIER_HEADS_UP:
        if heads_up_minutes <= 0:
            return None
        return leave_by - timedelta(minutes=heads_up_minutes)
    if tier == TIER_LEAVE_NOW:
        return leave_by
    if tier == TIER_LATE:
        if late_minutes <= 0:
            return None
        return leave_by + timedelta(minutes=late_minutes)
    return None


def classify_alert(
    now: datetime,
    due: datetime,
    event_start: datetime,
    grace_seconds: int = ALERT_GRACE_SECONDS,
) -> str:
    """Decide what to do with a tier: "wait", "fire" or "skip".

    * wait - not due yet
    * fire - due, within the grace window, and the event hasn't started
    * skip - due but too stale (e.g. Home Assistant was down) or event started
    """
    if now < due:
        return "wait"
    if now >= event_start:
        return "skip"
    if (now - due).total_seconds() > grace_seconds:
        return "skip"
    return "fire"


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_message(template: str, values: dict[str, Any]) -> str:
    """Fill {placeholders} in a message; unknown placeholders are left as-is."""
    try:
        return template.format_map(_SafeDict(values))
    except (ValueError, IndexError, KeyError):
        return template


def event_key(calendar: str, uid: str | None, summary: str, start: datetime) -> str:
    """Stable key identifying one occurrence of a calendar event."""
    return f"{calendar}|{uid or summary}|{start.isoformat()}"


def round_minutes(seconds: float) -> int:
    """Minutes rounded to the nearest whole minute (never negative)."""
    return max(0, int(round(seconds / 60)))


# "#transit" style tags. The lookbehind avoids HTML entities such as "&#39;".
_TAG_PATTERN = re.compile(r"(?<![\w&])#([A-Za-z]+)")


def parse_mode_tag(*texts: str | None) -> str | None:
    """Return the travel mode requested by a #tag in the given texts, if any.

    The first recognised tag wins, searching the texts in the order given.
    """
    for text in texts:
        if not text:
            continue
        for match in _TAG_PATTERN.finditer(text):
            mode = MODE_TAGS.get(match.group(1).lower())
            if mode:
                return mode
    return None
