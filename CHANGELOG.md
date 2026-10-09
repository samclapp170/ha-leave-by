# Changelog

## 0.1.0

First release.

- Guided setup interview (API key walkthrough, calendars, trip, countdown, alerts, lights, speakers, notifications) and an options menu to change any answer later.
- Calendar-driven leave-by countdown using the Google Routes API: driving with live traffic, walking, cycling, timetable-aware transit.
- Per-event travel mode via `#transit`, `#drive`, `#walk`, `#bike` tags.
- Configurable time to get to the car.
- Heads-up, leave-now and running-late alerts: light flash with per-alert colors, text-to-speech, phone notifications, and a `leave_by_alert` event.
- Alerts fire on exact time, once per event, and survive restarts.
- Sensors, a binary sensor, buttons, services, diagnostics and reauthentication.
