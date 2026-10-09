"""Config flow: a guided interview, plus an options menu to change answers later."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector as sel
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    RoutesApiDisabled,
    RoutesClient,
    RoutesConnectionError,
    RoutesError,
    RoutesInvalidKey,
    RoutesNoRoute,
    RoutesPermissionDenied,
    RoutesQuotaExceeded,
    place_latlng,
)
from .const import (
    CONF_API_KEY,
    CONF_BUFFER_MINUTES,
    CONF_CALENDARS,
    CONF_COLOR_HEADS_UP,
    CONF_COLOR_LATE,
    CONF_COLOR_LEAVE_NOW,
    CONF_COUNTDOWN_TYPE,
    CONF_EVENT_TAGS,
    CONF_FLASH_COUNT,
    CONF_FLASH_LENGTH,
    CONF_HEADS_UP_MINUTES,
    CONF_LATE_MINUTES,
    CONF_LIGHTS,
    CONF_LIVE_TRAFFIC,
    CONF_LOOKAHEAD_HOURS,
    CONF_MSG_HEADS_UP,
    CONF_MSG_LATE,
    CONF_MSG_LEAVE_NOW,
    CONF_NAME,
    CONF_NOTIFY,
    CONF_ORIGIN_ADDRESS,
    CONF_ORIGIN_ENTITY,
    CONF_ORIGIN_TYPE,
    CONF_POLL_MINUTES,
    CONF_RUN_TEST,
    CONF_SPEAKERS,
    CONF_TEST_ON_SETUP,
    CONF_TEXT_ENTITY,
    CONF_TEXT_STYLE,
    CONF_TICK_SECONDS,
    CONF_TIMER_ENTITY,
    CONF_TRAVEL_MODE,
    CONF_TTS_ENTITY,
    CONF_VOLUME,
    COUNTDOWN_TYPES,
    DEFAULTS,
    DOMAIN,
    FLASH_LENGTHS,
    MODE_DRIVE,
    NAME,
    ORIGIN_ADDRESS,
    ORIGIN_HOME,
    ORIGIN_TRACKER,
    ORIGIN_TYPES,
    TEXT_STYLES,
    TRAVEL_MODES,
)

_LOGGER = logging.getLogger(__name__)

STEP_ORDER = [
    "api_key",
    "calendars",
    "trip",
    "countdown",
    "alerts",
    "lights",
    "speakers",
    "notifications",
    "confirm",
]

INT_KEYS = {
    CONF_LOOKAHEAD_HOURS,
    CONF_POLL_MINUTES,
    CONF_BUFFER_MINUTES,
    CONF_TICK_SECONDS,
    CONF_HEADS_UP_MINUTES,
    CONF_LATE_MINUTES,
    CONF_FLASH_COUNT,
    CONF_VOLUME,
}

# Keys the user may leave empty/clear; removed from the working config before
# applying a submission so clearing a field really clears it.
OPTIONAL_KEYS = {
    "countdown": [CONF_TIMER_ENTITY, CONF_TEXT_ENTITY],
    "lights": [CONF_LIGHTS],
    "speakers": [CONF_SPEAKERS, CONF_TTS_ENTITY],
    "notifications": [CONF_NOTIFY],
}


def _number(minimum: float, maximum: float, unit: str | None = None, step: float = 1):
    return sel.NumberSelector(
        sel.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            mode=sel.NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


def _dropdown(options: list[str], translation_key: str):
    return sel.SelectSelector(
        sel.SelectSelectorConfig(
            options=options,
            mode=sel.SelectSelectorMode.DROPDOWN,
            translation_key=translation_key,
        )
    )


def _required(key: str, values: Mapping[str, Any]) -> vol.Required:
    return vol.Required(key, default=values.get(key, DEFAULTS.get(key)))


def _optional(key: str, values: Mapping[str, Any]) -> vol.Optional:
    return vol.Optional(key, description={"suggested_value": values.get(key)})


def _clean(user_input: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in user_input.items():
        if key in INT_KEYS and value is not None:
            value = int(value)
        elif isinstance(value, str):
            value = value.strip()
        out[key] = value
    return out


Validator = Callable[[dict[str, Any]], Awaitable[dict[str, str]]]


class _InterviewMixin:
    """The interview steps, shared by the first-run flow and the options menu."""

    _cfg: dict[str, Any]
    _options_mode: bool = False

    # Provided by the flow base classes.
    hass: Any
    async_show_form: Callable[..., ConfigFlowResult]

    # --------------------------------------------------------------- plumbing
    async def _advance(self, step_id: str) -> ConfigFlowResult:
        if step_id == "trip" and self._cfg.get(CONF_ORIGIN_TYPE) != ORIGIN_HOME:
            return await self.async_step_origin_detail()  # type: ignore[attr-defined]
        if self._options_mode:
            return await self.async_step_init()  # type: ignore[attr-defined]
        if step_id == "origin_detail":
            step_id = "trip"
        nxt = STEP_ORDER[STEP_ORDER.index(step_id) + 1]
        return await getattr(self, f"async_step_{nxt}")()

    async def _handle(
        self,
        step_id: str,
        user_input: dict[str, Any] | None,
        build: Callable[[Mapping[str, Any]], vol.Schema],
        validate: Validator | None = None,
        placeholders: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        values: Mapping[str, Any] = self._cfg
        if user_input is not None:
            cleaned = _clean(user_input)
            errors = await validate(cleaned) if validate else {}
            if not errors:
                for key in OPTIONAL_KEYS.get(step_id, []):
                    self._cfg.pop(key, None)
                self._cfg.update(cleaned)
                return await self._advance(step_id)
            values = {**self._cfg, **cleaned}
        return self.async_show_form(
            step_id=step_id,
            data_schema=build(values),
            errors=errors,
            description_placeholders=placeholders,
        )

    # ---------------------------------------------------------------- api key
    async def _check_key(self, key: str) -> dict[str, str]:
        client = RoutesClient(async_get_clientsession(self.hass), key)
        lat, lon = self.hass.config.latitude, self.hass.config.longitude
        try:
            # Cheapest possible request: no traffic, ~3 km hop from home.
            await client.compute(
                place_latlng(lat, lon),
                place_latlng(lat + 0.02, lon + 0.02),
                mode=MODE_DRIVE,
                traffic=False,
            )
        except RoutesInvalidKey:
            return {CONF_API_KEY: "invalid_api_key"}
        except RoutesApiDisabled:
            return {CONF_API_KEY: "api_not_enabled"}
        except RoutesPermissionDenied as err:
            _LOGGER.warning("Routes API refused the key: %s", err)
            return {CONF_API_KEY: "permission_denied"}
        except RoutesQuotaExceeded:
            return {CONF_API_KEY: "quota_exceeded"}
        except RoutesConnectionError:
            return {CONF_API_KEY: "cannot_connect"}
        except RoutesNoRoute:
            return {}  # The key works; there just was no road at that spot.
        except RoutesError as err:
            _LOGGER.warning("Unexpected Routes API error: %s", err)
            return {CONF_API_KEY: "unknown"}
        return {}

    async def async_step_api_key(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        def build(values: Mapping[str, Any]) -> vol.Schema:
            return vol.Schema(
                {
                    vol.Required(
                        CONF_API_KEY, default=values.get(CONF_API_KEY, "")
                    ): sel.TextSelector(
                        sel.TextSelectorConfig(type=sel.TextSelectorType.PASSWORD)
                    )
                }
            )

        async def validate(data: dict[str, Any]) -> dict[str, str]:
            return await self._check_key(data[CONF_API_KEY])

        return await self._handle("api_key", user_input, build, validate)

    # -------------------------------------------------------------- calendars
    async def async_step_calendars(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        def build(values: Mapping[str, Any]) -> vol.Schema:
            return vol.Schema(
                {
                    vol.Required(
                        CONF_CALENDARS, default=values.get(CONF_CALENDARS, [])
                    ): sel.EntitySelector(
                        sel.EntitySelectorConfig(domain="calendar", multiple=True)
                    ),
                    _required(CONF_LOOKAHEAD_HOURS, values): _number(1, 24, "h"),
                    _required(CONF_POLL_MINUTES, values): _number(2, 60, "min"),
                }
            )

        async def validate(data: dict[str, Any]) -> dict[str, str]:
            return {} if data.get(CONF_CALENDARS) else {CONF_CALENDARS: "no_calendars_selected"}

        return await self._handle("calendars", user_input, build, validate)

    # ------------------------------------------------------------------- trip
    async def async_step_trip(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        def build(values: Mapping[str, Any]) -> vol.Schema:
            return vol.Schema(
                {
                    _required(CONF_BUFFER_MINUTES, values): _number(0, 60, "min"),
                    _required(CONF_TRAVEL_MODE, values): _dropdown(
                        TRAVEL_MODES, "travel_mode"
                    ),
                    _required(CONF_EVENT_TAGS, values): sel.BooleanSelector(),
                    _required(CONF_LIVE_TRAFFIC, values): sel.BooleanSelector(),
                    _required(CONF_ORIGIN_TYPE, values): _dropdown(
                        ORIGIN_TYPES, "origin_type"
                    ),
                }
            )

        return await self._handle("trip", user_input, build)

    async def async_step_origin_detail(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        origin = self._cfg.get(CONF_ORIGIN_TYPE)

        def build(values: Mapping[str, Any]) -> vol.Schema:
            if origin == ORIGIN_TRACKER:
                return vol.Schema(
                    {
                        vol.Required(
                            CONF_ORIGIN_ENTITY,
                            default=values.get(CONF_ORIGIN_ENTITY, vol.UNDEFINED),
                        ): sel.EntitySelector(
                            sel.EntitySelectorConfig(domain=["person", "device_tracker"])
                        )
                    }
                )
            return vol.Schema(
                {
                    vol.Required(
                        CONF_ORIGIN_ADDRESS,
                        default=values.get(CONF_ORIGIN_ADDRESS, ""),
                    ): sel.TextSelector()
                }
            )

        async def validate(data: dict[str, Any]) -> dict[str, str]:
            if origin == ORIGIN_ADDRESS and not data.get(CONF_ORIGIN_ADDRESS):
                return {CONF_ORIGIN_ADDRESS: "address_required"}
            return {}

        # Drop whichever origin field no longer applies.
        stale = CONF_ORIGIN_ADDRESS if origin == ORIGIN_TRACKER else CONF_ORIGIN_ENTITY
        self._cfg.pop(stale, None)
        return await self._handle("origin_detail", user_input, build, validate)

    # -------------------------------------------------------------- countdown
    async def async_step_countdown(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        def build(values: Mapping[str, Any]) -> vol.Schema:
            return vol.Schema(
                {
                    _required(CONF_COUNTDOWN_TYPE, values): _dropdown(
                        COUNTDOWN_TYPES, "countdown_type"
                    ),
                    _required(CONF_TEXT_STYLE, values): _dropdown(
                        TEXT_STYLES, "text_style"
                    ),
                    _required(CONF_TICK_SECONDS, values): _number(1, 60, "s"),
                    _optional(CONF_TIMER_ENTITY, values): sel.EntitySelector(
                        sel.EntitySelectorConfig(domain="timer")
                    ),
                    _optional(CONF_TEXT_ENTITY, values): sel.EntitySelector(
                        sel.EntitySelectorConfig(domain="input_text")
                    ),
                }
            )

        return await self._handle("countdown", user_input, build)

    # ----------------------------------------------------------------- alerts
    async def async_step_alerts(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        def build(values: Mapping[str, Any]) -> vol.Schema:
            return vol.Schema(
                {
                    _required(CONF_HEADS_UP_MINUTES, values): _number(0, 180, "min"),
                    _required(CONF_LATE_MINUTES, values): _number(0, 60, "min"),
                }
            )

        return await self._handle("alerts", user_input, build)

    # ----------------------------------------------------------------- lights
    async def async_step_lights(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        def build(values: Mapping[str, Any]) -> vol.Schema:
            return vol.Schema(
                {
                    _optional(CONF_LIGHTS, values): sel.EntitySelector(
                        sel.EntitySelectorConfig(domain="light", multiple=True)
                    ),
                    _required(CONF_FLASH_LENGTH, values): _dropdown(
                        FLASH_LENGTHS, "flash_length"
                    ),
                    _required(CONF_FLASH_COUNT, values): _number(1, 5, "×"),
                    _required(CONF_COLOR_HEADS_UP, values): sel.ColorRGBSelector(),
                    _required(CONF_COLOR_LEAVE_NOW, values): sel.ColorRGBSelector(),
                    _required(CONF_COLOR_LATE, values): sel.ColorRGBSelector(),
                }
            )

        return await self._handle("lights", user_input, build)

    # --------------------------------------------------------------- speakers
    async def async_step_speakers(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if CONF_TTS_ENTITY not in self._cfg:
            tts = sorted(self.hass.states.async_entity_ids("tts"))
            if tts:
                self._cfg[CONF_TTS_ENTITY] = tts[0]

        def build(values: Mapping[str, Any]) -> vol.Schema:
            return vol.Schema(
                {
                    _optional(CONF_SPEAKERS, values): sel.EntitySelector(
                        sel.EntitySelectorConfig(domain="media_player", multiple=True)
                    ),
                    _optional(CONF_TTS_ENTITY, values): sel.EntitySelector(
                        sel.EntitySelectorConfig(domain="tts")
                    ),
                    _required(CONF_VOLUME, values): _number(0, 100, "%", step=5),
                    _required(CONF_MSG_HEADS_UP, values): sel.TextSelector(
                        sel.TextSelectorConfig(multiline=True)
                    ),
                    _required(CONF_MSG_LEAVE_NOW, values): sel.TextSelector(
                        sel.TextSelectorConfig(multiline=True)
                    ),
                    _required(CONF_MSG_LATE, values): sel.TextSelector(
                        sel.TextSelectorConfig(multiline=True)
                    ),
                }
            )

        async def validate(data: dict[str, Any]) -> dict[str, str]:
            if data.get(CONF_SPEAKERS) and not data.get(CONF_TTS_ENTITY):
                return {CONF_TTS_ENTITY: "tts_required"}
            return {}

        return await self._handle("speakers", user_input, build, validate)

    # ---------------------------------------------------------- notifications
    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        services = sorted(
            name
            for name in self.hass.services.async_services_for_domain("notify")
            if name != "send_message"
        )
        if not services:
            # Nothing to choose from; don't make the user click through an empty page.
            self._cfg.pop(CONF_NOTIFY, None)
            return await self._advance("notifications")

        def build(values: Mapping[str, Any]) -> vol.Schema:
            return vol.Schema(
                {
                    _optional(CONF_NOTIFY, values): sel.SelectSelector(
                        sel.SelectSelectorConfig(
                            options=services,
                            multiple=True,
                            mode=sel.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            )

        return await self._handle("notifications", user_input, build)


class LeaveByConfigFlow(_InterviewMixin, ConfigFlow, domain=DOMAIN):
    """First-run interview."""

    VERSION = 1

    def __init__(self) -> None:
        self._cfg = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> LeaveByOptionsFlow:
        return LeaveByOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Welcome page."""
        if not self.hass.states.async_entity_ids("calendar"):
            return self.async_abort(reason="no_calendars")
        if user_input is not None:
            return await self.async_step_api_key()
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            data = {CONF_API_KEY: self._cfg[CONF_API_KEY]}
            if user_input.get(CONF_RUN_TEST):
                data[CONF_TEST_ON_SETUP] = True
            options = {
                k: v
                for k, v in self._cfg.items()
                if k not in (CONF_API_KEY, CONF_NAME, CONF_RUN_TEST)
            }
            return self.async_create_entry(
                title=user_input[CONF_NAME].strip() or NAME,
                data=data,
                options=options,
            )

        have_outputs = any(
            self._cfg.get(k) for k in (CONF_LIGHTS, CONF_SPEAKERS, CONF_NOTIFY)
        )
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=NAME): str,
                    vol.Required(CONF_RUN_TEST, default=have_outputs): sel.BooleanSelector(),
                }
            ),
        )

    # ------------------------------------------------------------------ reauth
    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            key = user_input[CONF_API_KEY].strip()
            errors = await self._check_key(key)
            if not errors:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates={CONF_API_KEY: key}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): sel.TextSelector(
                        sel.TextSelectorConfig(type=sel.TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )


class LeaveByOptionsFlow(_InterviewMixin, OptionsFlow):
    """Re-run any part of the interview."""

    _options_mode = True

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if not hasattr(self, "_cfg"):
            self._cfg = {**DEFAULTS, **self.config_entry.data, **self.config_entry.options}
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "calendars",
                "trip",
                "countdown",
                "alerts",
                "lights",
                "speakers",
                "notifications",
                "api_key",
                "finish",
            ],
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self.config_entry
        new_key = self._cfg[CONF_API_KEY]
        if new_key != entry.data.get(CONF_API_KEY):
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_API_KEY: new_key}
            )
        options = {
            k: v
            for k, v in self._cfg.items()
            if k not in (CONF_API_KEY, CONF_NAME, CONF_RUN_TEST, CONF_TEST_ON_SETUP)
        }
        return self.async_create_entry(title="", data=options)
