# Home Assistant MCP for PETEY

[![PETEY Desktop](https://img.shields.io/badge/PETEY_Desktop-v0.19.0%2B-7f5af0)](https://github.com/bizzomephisto/PETEY-DESKTOP)
[![Release](https://img.shields.io/github/v/release/bizzomephisto/PETEY-HOME-ASSISTANT)](https://github.com/bizzomephisto/PETEY-HOME-ASSISTANT/releases/latest)
[![Tests](https://github.com/bizzomephisto/PETEY-HOME-ASSISTANT/actions/workflows/test.yml/badge.svg)](https://github.com/bizzomephisto/PETEY-HOME-ASSISTANT/actions/workflows/test.yml)

This add-on connects PETEY directly to Home Assistant's official MCP Server
integration at `/api/mcp/assist`. It does not install or launch another MCP server.

Current version: **1.2.1**

## Requirements

- [PETEY Desktop v0.19.0 or newer](https://github.com/bizzomephisto/PETEY-DESKTOP/releases/latest)
- A reachable Home Assistant installation with **Model Context Protocol Server** enabled
- A Home Assistant long-lived access token

## Install

1. Download `petey-home-assistant-v1.2.1.zip` from the [latest release](https://github.com/bizzomephisto/PETEY-HOME-ASSISTANT/releases/latest).
2. Extract the archive. It contains one folder named `home-assistant`.
3. Copy that folder into PETEY's add-ons directory.
4. Enable **Home Assistant MCP** and restart PETEY.

## Configuration

1. In Home Assistant, install **Model Context Protocol Server** under **Settings →
   Devices & services** and choose **Control Home Assistant** during setup. In Home
   Assistant 2026.9, this integration does not provide a later Configure/Options
   screen; remove and add it again if that initial selection must be changed.
2. Expose only the desired entities under **Settings → Voice assistants → Expose**.
3. Open PETEY's **Home Assistant** screen, paste a long-lived access token, and
   choose **Save & connect**. PETEY stores it as `HOMEASSISTANT_TOKEN` in the
   private project `.env` file. You can alternatively add these lines manually:

   ```dotenv
   HOMEASSISTANT_URL=http://homeassistant.local:8123
   HOMEASSISTANT_TOKEN=your-long-lived-access-token
   ```

4. Enable the add-on in PETEY and restart PETEY. It connects automatically when
   the environment credential is present.

## Alert relay

Enable **Relay Home Assistant alerts** in the add-on panel. PETEY opens Home
Assistant's authenticated `/api/websocket` stream and listens for:

- `alert.*` entities changing to `on`, and optionally returning to `idle`.
- Custom `petey_alert` events containing a `title`, `message`, and optional `speak`.

PETEY receives the alert as a hidden add-on event, responds in the active chat, and
speaks when both the add-on option and that device's global speaker control allow it.
The editable prompt supports `{title}`, `{message}`, `{status}`, and `{entity_id}`.
Identical Home Assistant event context IDs are processed once.

To send a detailed alert from any Home Assistant automation, use its **Fire Manual
Event** action or this YAML action:

```yaml
- event: petey_alert
  event_data:
    title: "Front door"
    message: "The front door has been open for five minutes."
    speak: true
```

The relay reconnects automatically after a Home Assistant restart or temporary
network interruption. Use **Send test alert** in PETEY to verify the chat and speech
path without waiting for an automation.

## Entity vocabulary

Open the Home Assistant panel and choose **Scan exposed entities**. PETEY builds a
batch editor from the official Assist MCP live context. For any entity, add:

- **Call it…** — one or more everyday names separated by commas.
- **Meaning** — optional context such as who a pet is, what a technical sensor means,
  or where a device is located.

Choose **Save all** once after editing any number of rows. These mappings stay in
PETEY's private add-on data and never rename or reconfigure Home Assistant. Saved
names activate live lookups, are translated to the exact Home Assistant friendly
name before filtered reads or actions, and are included with live results so the
model can explain technical domains in household language. Scan again whenever the
set of exposed entities changes; existing edits are merged by official name.

The token is accepted only by the local save endpoint, written atomically with
owner-only permissions, loaded into the current PETEY process, and never returned
to the browser, logs, tool schemas, or API responses. The alternate names
`HOME_ASSISTANT_URL` and `HOME_ASSISTANT_TOKEN` are also read for compatibility.

## Device changes

Only tools served by the official Assist MCP endpoint are considered. Live context
reads run immediately. Home Assistant action tools use component namespaces such
as `intent__HassTurnOn` and `light__HassLightSet`; these create ten-minute proposals
by default. Enable **Trust PETEY with device changes** to run those requested
actions immediately. Non-action MCP tools outside the live-context allowlist
remain blocked.

PETEY treats friendly entity names as the user-facing device type. Home Assistant
may classify an automatic litter box under the `vacuum` domain because it reuses the
vacuum service model; PETEY should still call it a litter box. Device integration
enablement and Assist exposure are separate. Expose each related sensor individually
when PETEY should see values such as litter level, waste drawer, weight, or battery.
Read-only entity-name questions such as “do you see anything named …?” also trigger
a fresh live-context lookup even when the name itself contains no smart-home keyword.
If Home Assistant rejects a partial friendly-name filter, the add-on automatically
retries with the full exposed context so household nicknames can still be resolved.
Pet measurements and activity terms such as weight, visits, litter, hopper, and waste
drawer also activate a fresh read without requiring the words “Home Assistant.”

The Home Assistant MCP documentation is at
<https://www.home-assistant.io/integrations/mcp_server>.
The live event transport follows Home Assistant's WebSocket API:
<https://developers.home-assistant.io/docs/api/websocket/>.
