"""Constants for the Leave By integration."""

from __future__ import annotations

DOMAIN = "leave_by"
NAME = "Leave By"

# --- Setup / calendars -------------------------------------------------------
CONF_API_KEY = "api_key"
CONF_CALENDARS = "calendars"
CONF_LOOKAHEAD_HOURS = "lookahead_hours"
CONF_POLL_MINUTES = "poll_minutes"

# --- Trip --------------------------------------------------------------------
CONF_ORIGIN_TYPE = "origin_type"
CONF_ORIGIN_ENTITY = "origin_entity"
CONF_ORIGIN_ADDRESS = "origin_address"
CONF_TRAVEL_MODE = "travel_mode"
CONF_LIVE_TRAFFIC = "live_traffic"
CONF_BUFFER_MINUTES = "buffer_minutes"
CONF_EVENT_TAGS = "event_tags"

ORIGIN_HOME = "home"
ORIGIN_TRACKER = "tracker"
ORIGIN_ADDRESS = "address"
ORIGIN_TYPES = [ORIGIN_HOME, ORIGIN_TRACKER, ORIGIN_ADDRESS]

MODE_DRIVE = "DRIVE"
MODE_WALK = "WALK"
MODE_BICYCLE = "BICYCLE"
MODE_TRANSIT = "TRANSIT"
TRAVEL_MODES = [MODE_DRIVE, MODE_WALK, MODE_BICYCLE, MODE_TRANSIT]

# Hashtags in an event's title or description that pick its travel mode.
MODE_TAGS: dict[str, str] = {
    "drive": MODE_DRIVE,
    "driving": MODE_DRIVE,
    "car": MODE_DRIVE,
    "walk": MODE_WALK,
    "walking": MODE_WALK,
    "bike": MODE_BICYCLE,
    "biking": MODE_BICYCLE,
    "bicycle": MODE_BICYCLE,
    "cycle": MODE_BICYCLE,
    "transit": MODE_TRANSIT,
    "bus": MODE_TRANSIT,
    "train": MODE_TRANSIT,
    "subway": MODE_TRANSIT,
    "metro": MODE_TRANSIT,
    "rail": MODE_TRANSIT,
}

# --- Countdown ---------------------------------------------------------------
CONF_COUNTDOWN_TYPE = "countdown_type"
CONF_TEXT_STYLE = "text_style"
CONF_TICK_SECONDS = "tick_seconds"
CONF_TIMER_ENTITY = "timer_entity"
CONF_TEXT_ENTITY = "text_entity"

COUNTDOWN_LEAVE_BY = "leave_by"
COUNTDOWN_EVENT_START = "event_start"
COUNTDOWN_TYPES = [COUNTDOWN_LEAVE_BY, COUNTDOWN_EVENT_START]

STYLE_FRIENDLY = "friendly"
STYLE_CLOCK = "clock"
TEXT_STYLES = [STYLE_FRIENDLY, STYLE_CLOCK]

# --- Alerts ------------------------------------------------------------------
CONF_HEADS_UP_MINUTES = "heads_up_minutes"
CONF_LATE_MINUTES = "late_minutes"

TIER_HEADS_UP = "heads_up"
TIER_LEAVE_NOW = "leave_now"
TIER_LATE = "late"
TIERS = [TIER_HEADS_UP, TIER_LEAVE_NOW, TIER_LATE]

# --- Lights ------------------------------------------------------------------
CONF_LIGHTS = "lights"
CONF_FLASH_LENGTH = "flash_length"
CONF_FLASH_COUNT = "flash_count"
CONF_COLOR_HEADS_UP = "color_heads_up"
CONF_COLOR_LEAVE_NOW = "color_leave_now"
CONF_COLOR_LATE = "color_late"

FLASH_SHORT = "short"
FLASH_LONG = "long"
FLASH_LENGTHS = [FLASH_SHORT, FLASH_LONG]
FLASH_SECONDS = {FLASH_SHORT: 2, FLASH_LONG: 10}

# --- Speakers / notifications ------------------------------------------------
CONF_SPEAKERS = "speakers"
CONF_TTS_ENTITY = "tts_entity"
CONF_VOLUME = "volume"
CONF_MSG_HEADS_UP = "message_heads_up"
CONF_MSG_LEAVE_NOW = "message_leave_now"
CONF_MSG_LATE = "message_late"
CONF_NOTIFY = "notify_services"

# --- Flow-only / internal ----------------------------------------------------
CONF_NAME = "name"
CONF_RUN_TEST = "run_test"
CONF_TEST_ON_SETUP = "test_on_setup"

DEFAULTS: dict = {
    CONF_LOOKAHEAD_HOURS: 4,
    CONF_POLL_MINUTES: 10,
    CONF_ORIGIN_TYPE: ORIGIN_HOME,
    CONF_TRAVEL_MODE: MODE_DRIVE,
    CONF_LIVE_TRAFFIC: True,
    CONF_BUFFER_MINUTES: 5,
    CONF_EVENT_TAGS: True,
    CONF_COUNTDOWN_TYPE: COUNTDOWN_LEAVE_BY,
    CONF_TEXT_STYLE: STYLE_CLOCK,
    CONF_TICK_SECONDS: 15,
    CONF_HEADS_UP_MINUTES: 30,
    CONF_LATE_MINUTES: 0,
    CONF_FLASH_LENGTH: FLASH_LONG,
    CONF_FLASH_COUNT: 1,
    CONF_COLOR_HEADS_UP: [255, 170, 0],
    CONF_COLOR_LEAVE_NOW: [0, 255, 0],
    CONF_COLOR_LATE: [255, 0, 0],
    CONF_VOLUME: 0,
    CONF_MSG_HEADS_UP: "Heads up. Time to leave for {event} in {minutes} minutes.",
    CONF_MSG_LEAVE_NOW: "Time to leave for {event}. Travel time is {travel_minutes} minutes.",
    CONF_MSG_LATE: "You are running late for {event}. You should have left {minutes_late} minutes ago.",
}

# Alerts older than this (relative to when they were due) are skipped rather
# than fired, e.g. after Home Assistant was offline.
ALERT_GRACE_SECONDS = 15 * 60
# Travel-time lookups newer than this are reused instead of calling the API.
TRAVEL_CACHE_SECONDS = 90
# Stale estimates are still used as a fallback if the API fails, up to this age.
TRAVEL_STALE_MAX_SECONDS = 2 * 60 * 60

EVENT_ALERT = f"{DOMAIN}_alert"

PLATFORMS = ["sensor", "binary_sensor", "button"]
