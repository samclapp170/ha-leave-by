# Leave By for Home Assistant

[![hacs][hacs-badge]][hacs-url] [![Validate][ci-badge]][ci-url]

**Your calendar knows when the event starts. Leave By tells you when to *leave*.**

Leave By watches your calendar for timed events that have a location, asks Google Maps how long the trip will really take, and counts down to the moment you need to head out: event start, minus travel time, minus the time it takes you to get to your car. It can flash lights, speak on speakers and notify your phone, and every part of that is set up through a guided interview (no YAML).

It was built for people who are great at meeting the time they *see* and bad at meeting the time they *need*: an honest, ambient countdown that is hard to talk yourself out of.

## Features

- **Guided setup.** Walks you through getting a Google Maps API key, choosing calendars, your travel mode, the countdown type, and which lights, speakers and phones to use. Every answer can be changed later from **Configure**.
- **Works with any calendar in Home Assistant**: Google Calendar, CalDAV, iCloud, Microsoft 365, Local Calendar, and so on.
- **Real travel time.** Live-traffic driving, walking, cycling or public transit via the Google Routes API.
- **Pick the travel mode per event** with a hashtag in the event title or description: `#transit`, `#drive`, `#walk`, `#bike`.
- **Timetable-aware transit.** Finds a trip that arrives by the event start and works back from when the first vehicle actually boards, minus your walk to the stop.
- **Your own "get to the car" buffer** (5 minutes by default).
- **Up to three alerts per event**: heads-up, leave now, running late. Each has its own light color and spoken message.
- **Alerts fire exactly on time** (not "within the next polling cycle") and **only once per event**, even if Home Assistant restarts.
- **Failure-tolerant.** A flaky speaker or an offline light never blocks the other alerts; announcements retry once.
- **Countdown entities for dashboards and native-app widgets** that tick locally without using Google requests.
- **"Skip current event" button** for the "I'm already in the car" moments.

## Install

### With HACS (recommended)

1. In HACS, open the menu (⋮) → **Custom repositories**.
2. Add `https://github.com/samclapp170/ha-leave-by` with category **Integration**.
3. Install **Leave By**, then **restart Home Assistant**.

### Manually

Copy `custom_components/leave_by` into your Home Assistant `config/custom_components/` folder and restart.

Requires Home Assistant 2025.1 or newer.

## Setup

Go to **Settings → Devices & services → Add integration → Leave By** and answer the interview:

| Step | You choose |
|---|---|
| 1. Google Maps API key | Step-by-step instructions are shown in the dialog. The key is tested when you submit it. |
| 2. Calendars | Which calendar(s) to watch, how far ahead to look (default 4 hours), how often to re-check traffic (default 10 minutes). |
| 3. Your trip | Time to get to your car / out the door, your usual travel mode, whether `#tags` can override it, live traffic, and where trips start (home, a person or device for live location, or a fixed address). |
| 4. The countdown | Count down to **time to leave** or to **event start**; clock (`42:10`) or friendly (`42m`) text; how often the display updates; optionally drive a `timer` helper and an `input_text` helper (see below). |
| 5. Alert timing | Heads-up minutes before leaving (0 = off), and an optional running-late nag. |
| 6. Lights | Which lights to flash, flash length and count, and a color for each alert. |
| 7. Speakers | Which speakers, which text-to-speech service, optional volume, and the message for each alert. |
| 8. Name | Name the tracker and optionally send a test alert right away. |

Lights, speakers and phone notifications are all optional. Skip any you don't have.

### Getting a Google Maps API key

The interview shows these steps with links; they are repeated here for reference.

1. Create a project in the [Google Cloud console](https://console.cloud.google.com/projectcreate).
2. [Set up billing](https://console.cloud.google.com/billing) for it. Google requires a billing account even though there is a monthly free allowance.
3. [Enable the Routes API](https://console.cloud.google.com/apis/library/routes.googleapis.com).
4. Create an API key under [Credentials](https://console.cloud.google.com/apis/credentials).
5. Restrict the key to **Routes API** only. Leave *Application restrictions* on **None** (Home Assistant calls Google from your server and home IP addresses change).
6. Add a [budget alert](https://console.cloud.google.com/billing/budgets) as a safety net.

**Cost.** Leave By makes one Routes request per upcoming event each time it re-checks (every 10 minutes by default), plus one extra when an alert is about to fire so it uses fresh traffic. Live-traffic driving requests are billed at a higher Google rate than basic ones, and Google's free allowance and prices change, so check [Google's pricing page](https://developers.google.com/maps/billing-and-pricing/pricing). To cut usage: lower the look-ahead window, raise the re-check interval, or turn off live traffic.

## Choosing the travel mode for one event

Put a tag in the event's **title** or **description**:

| Tag | Mode |
|---|---|
| `#transit` `#bus` `#train` `#subway` `#metro` `#rail` | Public transit |
| `#drive` `#car` | Driving |
| `#walk` | Walking |
| `#bike` `#cycle` | Cycling |

Example: `Choir rehearsal #transit`. Events without a tag use your usual mode. Turn this off in **Configure → Trip** if you'd rather not use it.

For transit, the leave-by time is the first vehicle's boarding time minus your walk to the stop and your buffer. You'll usually arrive a few minutes early, because Leave By picks a trip that arrives *by* the start time.

## What gets counted

An event is tracked when it:

- has a specific time (all-day events are ignored),
- has a location that isn't just a video-call link (Zoom, Meet, Teams and similar are ignored),
- starts within your look-ahead window.

If a travel time can't be found for an address, the event is skipped and listed in the `skipped_events` attribute of the **Next event** sensor.

## Entities

Everything lives on one device per tracker.

| Entity | What it is |
|---|---|
| `sensor.leave_by_next_event` | Name of the event being counted down to. Attributes: location, calendar, start, leave-by, travel mode, travel minutes, upcoming events. |
| `sensor.leave_by_leave_by` | Timestamp of the moment to leave. |
| `sensor.leave_by_event_start` | Timestamp of the event start. |
| `sensor.leave_by_travel_time` | Current travel estimate in minutes (attribute: without traffic). |
| `sensor.leave_by_seconds_remaining` | Seconds until your chosen countdown target. Negative once you are late. |
| `sensor.leave_by_countdown` | The same, as text: `42:10`, `1:05:09`, `-03:12`, or `No trips`. |
| `binary_sensor.leave_by_time_to_leave` | On from the leave-by moment until the event starts. |
| `button.leave_by_send_test_alert` | Runs your lights, speakers and notifications now. |
| `button.leave_by_skip_current_event` | Stops alerting for the current event. |
| `button.leave_by_refresh_now` | Re-reads calendars and travel times. |

Entity IDs depend on the name you gave the tracker.

The two ticking sensors update every few seconds (your choice) from stored data, so they never cost a Google request. If you use the Recorder, you may want to exclude them from history.

### Native apps and widgets

Some apps (for example Flux Dashboard) can only show an entity's **state**, not its attributes, and can't render custom Lovelace cards. Use `sensor.leave_by_countdown` (text) or `sensor.leave_by_seconds_remaining` (number) there.

### Timer-based cards

If your dashboard uses a card built around a `timer` helper, create a timer (and optionally an `input_text` helper) in **Settings → Devices & services → Helpers**, and select them in the **Countdown** step. Leave By starts, restarts and cancels the timer for you and writes the event name into the text helper. Leave By never touches helpers you don't select.

## Services and events

| Service | Purpose |
|---|---|
| `leave_by.refresh` | Re-read calendars and travel times. |
| `leave_by.test_alert` | Simulate `heads_up`, `leave_now` or `late` using a made-up event. |
| `leave_by.dismiss_event` | Skip the current event. |

All three take an optional `config_entry_id` (default: every tracker).

Each alert also fires a `leave_by_alert` event on the bus, so you can add your own actions:

```yaml
automation:
  - alias: "Leave By: turn the porch light on"
    triggers:
      - trigger: event
        event_type: leave_by_alert
        event_data:
          tier: leave_now
    actions:
      - action: light.turn_on
        target:
          entity_id: light.porch
```

Event data: `tier`, `message`, `event`, `location`, `minutes`, `minutes_late`, `travel_minutes`, `leave_time`, `start_time`, `leave_by`, `event_start`, `calendar`.

## Messages

Spoken and notification messages can use `{event}`, `{minutes}`, `{travel_minutes}`, `{minutes_late}`, `{location}`, `{leave_time}` and `{start_time}`.

## Good to know

- **Lights** are flashed with Home Assistant's `light.turn_on` `flash` option and return to their previous state (including off). Lights that don't support flashing may simply turn on. Color only applies to color-capable bulbs.
- **Speaker volume** is set before an announcement if you choose a volume, but is not restored afterwards. Leave it at 0 to keep each speaker's own volume.
- **Missed alerts.** If Home Assistant was offline when an alert was due, it is skipped rather than announced more than 15 minutes late.
- **Privacy.** Event locations, your origin, and your API key are sent to Google's Routes API to compute travel times. Nothing else leaves your system. Diagnostics downloads redact the key, addresses and event names.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "The Routes API isn't enabled" | Enable it (setup step 3) and wait a minute. |
| "Google refused the request" | Usually billing isn't set up, or the key's restrictions are wrong. Allow **Routes API** and set Application restrictions to **None**. |
| An event isn't counted | It needs a time (not all-day), a real address (not a video link), and to be inside the look-ahead window. Check `skipped_events` on the Next event sensor. |
| Alert didn't fire | Check the alert isn't set to 0 minutes, and try **Send test alert**. Alerts older than 15 minutes when first seen are skipped. |
| Re-authentication prompt | Google rejected the key. Enter a new one when prompted. |

Enable debug logging:

```yaml
logger:
  logs:
    custom_components.leave_by: debug
```

## Development

```bash
pip install -r requirements_test.txt
pytest
```

## License

MIT

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-orange.svg
[hacs-url]: https://hacs.xyz
[ci-badge]: https://github.com/samclapp170/ha-leave-by/actions/workflows/validate.yml/badge.svg
[ci-url]: https://github.com/samclapp170/ha-leave-by/actions/workflows/validate.yml
