# Home Assistant MCP for PETEY

[![PETEY Desktop](https://img.shields.io/badge/PETEY_Desktop-v0.18.2%2B-7f5af0)](https://github.com/bizzomephisto/PETEY-DESKTOP)
[![Release](https://img.shields.io/github/v/release/bizzomephisto/PETEY-HOME-ASSISTANT)](https://github.com/bizzomephisto/PETEY-HOME-ASSISTANT/releases/latest)
[![Tests](https://github.com/bizzomephisto/PETEY-HOME-ASSISTANT/actions/workflows/test.yml/badge.svg)](https://github.com/bizzomephisto/PETEY-HOME-ASSISTANT/actions/workflows/test.yml)

Connect [PETEY Desktop](https://github.com/bizzomephisto/PETEY-DESKTOP) to Home Assistant's official Assist MCP endpoint. PETEY can inspect exposed entity state, understand household names, and perform requested device actions through an approval queue or an optional trust mode.

This add-on connects directly to `/api/mcp/assist`. It does not install or launch another MCP server.

## Features

- Uses Home Assistant's official **Model Context Protocol Server** integration.
- Discovers only tools advertised by the official Assist endpoint and filters them through PETEY's allowlist.
- Reads exposed entity state immediately.
- Holds device-changing actions for review by default.
- Offers **Trust PETEY with device changes** for explicitly requested automatic actions.
- Builds a private entity vocabulary with custom everyday names and descriptions.
- Keeps the Home Assistant token out of API responses, logs, tool schemas, and repository files.
- Can be allowed in PETEY's Discord bridge with PETEY's separate per-add-on permission.

## Requirements

- [PETEY Desktop v0.18.2 or newer](https://github.com/bizzomephisto/PETEY-DESKTOP/releases)
- A reachable Home Assistant installation
- Home Assistant's **Model Context Protocol Server** integration
- A Home Assistant long-lived access token

## Install

1. Download `petey-home-assistant-v1.1.0.zip` from the [latest release](https://github.com/bizzomephisto/PETEY-HOME-ASSISTANT/releases/latest).
2. Extract the archive. It contains one folder named `home-assistant`.
3. In PETEY, open **Add-ons** and select **Open add-ons folder**.
4. Copy the complete `home-assistant` folder into that directory.
5. Return to PETEY, enable **Home Assistant MCP**, and restart PETEY.

For a source checkout, copy this repository's contents into a folder named `home-assistant` under PETEY's add-ons directory.

## Configure Home Assistant

1. In Home Assistant, open **Settings → Devices & services**.
2. Add **Model Context Protocol Server** and choose **Control Home Assistant** during setup. Some Home Assistant versions do not provide a later Configure/Options screen; remove and add the integration again if that initial selection must change.
3. Open **Settings → Voice assistants → Expose** and expose only the entities PETEY should access.
4. Create a long-lived access token from your Home Assistant profile.
5. Open PETEY's **Home Assistant** screen, enter the server address and token, then choose **Save & connect**.

The default address is `http://homeassistant.local:8123`. PETEY saves the token as `HOMEASSISTANT_TOKEN` in PETEY's private project `.env` file. You can configure it manually:

```dotenv
HOMEASSISTANT_URL=http://homeassistant.local:8123
HOMEASSISTANT_TOKEN=your-long-lived-access-token
```

The alternate names `HOME_ASSISTANT_URL` and `HOME_ASSISTANT_TOKEN` are also supported. Never commit `.env`.

## Teach PETEY household names

Open the Home Assistant panel and select **Scan exposed entities**. For each entity, you can add:

- **Call it…** — everyday names separated by commas.
- **Meaning** — context such as who a pet is, what a technical sensor measures, or where a device is located.

Select **Save all** after editing. These mappings remain in PETEY's private add-on data and do not rename Home Assistant entities. Scan again after exposing new entities; existing mappings are retained.

Home Assistant integrations sometimes use a technical domain that does not match the real object. For example, an automatic litter box may use the `vacuum` domain. PETEY uses the friendly name and your saved meaning when explaining it.

## Device-change safety

Live context reads run immediately. Device-changing MCP tools create ten-minute proposals by default. Review them from PETEY's Home Assistant panel.

Enable **Trust PETEY with device changes** to execute actions immediately when the user's request clearly asks for the change. Unknown MCP tools remain blocked. PETEY's optional Discord permission is separate and defaults off.

## Storage and privacy

- Connection URL, trust preference, and entity vocabulary: `addon-data/home-assistant/config.json`
- Token: PETEY's private `.env`
- Add-on source: `addons/home-assistant/`

The token save endpoint accepts the secret but never returns it. Writes are atomic and owner-only on supported platforms.

## Development

The add-on uses only PETEY's existing Python dependencies. To test it beside a PETEY Desktop checkout:

```bash
PYTHONPATH=/path/to/PETEY-DESKTOP python -m unittest discover -s tests -v
```

The manifest targets PETEY add-on API version `1`. See PETEY's [add-on authoring contract](https://github.com/bizzomephisto/PETEY-DESKTOP/blob/main/docs/addons.md) for host behavior and security requirements.

Home Assistant MCP documentation: <https://www.home-assistant.io/integrations/mcp_server>
