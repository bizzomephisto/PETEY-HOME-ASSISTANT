# Changelog

## v1.2.1 — 2026-09-23

- Keep the saved alert-relay preference enabled while its background listener starts.
- Report connection state separately so a temporary Home Assistant outage does not
  silently turn the user's relay setting back off.

## v1.2.0 — 2026-09-23

- Relay `alert.*` state changes and custom `petey_alert` events into PETEY chat.
- Add optional spoken alert announcements that respect PETEY's global speaker mute.
- Add an editable announcement prompt, recovery after disconnects, duplicate-event
  suppression, idle notifications, and a local test-alert control.

## v1.1.1 — 2026-09-22

- Recognize `litterbox`, `litter-box`, and `litter robot` as live Home Assistant status requests.
- Keep those read-only phrases from accidentally matching device-action tools.

## v1.1.0 — 2026-09-19

- Connect to Home Assistant's official Assist MCP endpoint.
- Discover exposed entities and build a private household vocabulary.
- Review device-changing actions or enable explicit trust mode.
- Retry partial entity-name lookups against the complete exposed context.
- Handle technical domains such as `vacuum` using friendly entity names.
- Store long-lived access tokens privately without returning them to the browser.
