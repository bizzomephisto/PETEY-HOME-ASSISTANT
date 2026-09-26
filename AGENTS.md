# Home Assistant MCP coding-agent context

Scope: this repository. Current add-on version: 1.2.1; PETEY add-on API: 1.
Read PETEY Desktop's `ADDONS.md` and `docs/addons.md` before changing host-facing
contracts. Source and tests win if this guide drifts.

## Product boundary

This add-on connects PETEY to Home Assistant's official MCP Server integration at
`/api/mcp/assist`. It never installs an MCP server and exposes only the official
Assist tools selected by its allowlist. Live context reads may execute directly.
Device changes create ten-minute review proposals unless the user explicitly turns
on the persisted trust option. The WebSocket alert relay is independently opt-in.

Credentials are private. The panel may accept a long-lived token, but public status,
tool schemas, logs, and error messages must never return it. The preferred environment
names are `HOMEASSISTANT_URL` and `HOMEASSISTANT_TOKEN`; compatibility aliases are
also supported. A saved token is written atomically to PETEY's private `.env` with
owner-only permissions where the filesystem supports them.

## Architecture and data flow

- `petey-addon.json` declares ID `home-assistant`, the panel assets, and API version.
- `addon.py:HomeAssistantAddon` owns configuration, credential lookup, the MCP HTTP
  session, proposal expiry, entity vocabulary, alert listener, and tool catalog.
- `connect()` initializes and discovers the bounded official Assist catalog;
  `disconnect()` and `close()` stop all connection and alert state.
- `_rpc()` handles MCP JSON-RPC/SSE responses with bounded parsing. `call_read()` is
  the read path. `request_action()` and `review()` enforce proposal or trusted action
  semantics at dispatch time as well as schema-offer time.
- `scan_entities()`, `_rewrite_arguments()`, and `_vocabulary_guidance()` map private
  household aliases to exact live friendly names without renaming Home Assistant.
- `_alert_worker()` owns the reconnecting thread/event-loop boundary.
  `_alert_connection()` authenticates to `/api/websocket`; `_handle_alert_message()`
  deduplicates context IDs; `_relay_alert()` emits one hidden PETEY event.
- `setup(context)` registers only `/api/addons/home-assistant/*` routes and returns
  the add-on instance so PETEY can obtain `tool_specs()` and call `close()`.
- `panel.html`, `panel.js`, and `panel.css` provide connection, token, trust,
  vocabulary, and alert controls. Mutations require a same-origin request.
- Writable config and vocabulary belong in `context.data_dir`, never this source tree.

## Preserve these contracts

- Never broaden tool exposure beyond the reviewed official Assist allowlist.
- Treat component action namespaces as consequential even when upstream metadata is
  incomplete. Default them to proposals; exactly one approval may execute a proposal.
- Tool availability and handler dispatch must both enforce connection and policy.
- Keep responses, schemas, entity lists, proposal counts, and error text bounded.
- A failed partial-name live-context filter retries once without the filter; it must
  not silently fabricate a device match.
- Reject ambiguous vocabulary aliases and rewrite only validated target fields.
- Alert relay remains opt-in, deduplicates upstream context IDs, obeys the event's
  `speak` flag plus PETEY's speaker state, and reconnects without busy looping.
- Keep config writes atomic. Never place tokens in the manifest, browser state,
  emitted event metadata, or model context.
- Disabled add-on discovery must not contact Home Assistant or start threads.

## Task map

| Task | Primary anchors |
| --- | --- |
| Connection/MCP parsing | `addon.py:_rpc`, `connect`, `disconnect`, `status` |
| Read/action policy | `call_read`, `request_action`, `review`, `tool_specs` |
| Entity aliases | `scan_entities`, `save_entity_vocabulary`, `_rewrite_arguments` |
| Alerts | `_start_alert_listener`, `_alert_connection`, `_relay_alert` |
| Credentials/config | `_token`, `save_token`, `configure`, `_write_config` |
| HTTP API | `setup`; matching controls in `panel.js` |
| Regression coverage | `tests/test_addon.py` |

## Validation

Run offline tests beside a PETEY Desktop checkout:

```bash
PYTHONPATH=/path/to/PETEY-DESKTOP python -m unittest discover -s tests -v
python -m py_compile addon.py
python -m json.tool petey-addon.json >/dev/null
node --check panel.js
```

Tests use fake HTTP/WebSocket boundaries and must not read live credentials, contact
Home Assistant, or perform device actions. For a release, bump the manifest and
README/changelog together, build a ZIP containing one `home-assistant/` folder, and
verify install/update behavior against a dedicated Home Assistant test instance.
