# Changelog

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
