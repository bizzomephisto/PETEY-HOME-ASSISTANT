import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask
from petey.addons import AddonManager


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("petey_home_assistant_test", ROOT / "addon.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Response:
    status_code = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, payload):
        self.payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self.payload


class FakeHTTP:
    def __init__(self):
        self.calls = []
        self.tools = [
            {"name": "homeassistant__GetLiveContext", "description": "Current state", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "intent__HassTurnOn", "description": "Turn on an entity", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
            {"name": "light__HassLightSet", "description": "Set a light", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "todo__get_items", "description": "Unsupported non-Hass tool", "inputSchema": {"type": "object"}},
            {"name": "custom__DeleteEverything", "description": "Unknown", "inputSchema": {"type": "object"}},
        ]

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        request = kwargs["json"]
        if request["method"] == "tools/list":
            result = {"tools": self.tools}
        elif (
            request["method"] == "tools/call"
            and request.get("params", {}).get("name") == "homeassistant__GetLiveContext"
            and request.get("params", {}).get("arguments") == {}
        ):
            context = (
                "Live Context: An overview of exposed entities:\n"
                "- names: Atlas Weight, atlas weight\n"
                "  domain: sensor\n"
                "  state: '12.87'\n"
                "  areas: Upstairs\n"
                "- names: Litter Robot\n"
                "  domain: vacuum\n"
                "  state: docked\n"
            )
            result = {
                "content": [{
                    "type": "text",
                    "text": json.dumps({"success": True, "result": context}),
                }],
                "isError": False,
            }
        elif request.get("params", {}).get("arguments", {}).get("name") == "poopcentral":
            result = {
                "content": [{
                    "type": "text",
                    "text": '{"success": false, "error": "No exposed entities matched name poopcentral"}',
                }],
                "isError": False,
            }
        elif request.get("params", {}).get("arguments", {}).get("name") == "Missing light":
            result = {
                "content": [{"type": "text", "text": "Error calling tool: <MatchFailedError>"}],
                "isError": True,
            }
        else:
            result = {"content": [{"type": "text", "text": "ok"}], "isError": False}
        return Response({"jsonrpc": "2.0", "id": request["id"], "result": result})


class HomeAssistantAddonTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(
            os.environ,
            {"HOMEASSISTANT_TOKEN": "secret-token", "HOMEASSISTANT_URL": "http://homeassistant.local:8123"},
            clear=False,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.http = FakeHTTP()
        self.env_path = Path(self.directory.name) / ".env"
        self.env_path.write_text("GEMINI_API_KEY=keep-me\n", encoding="utf-8")
        self.addon = MODULE.HomeAssistantAddon(
            SimpleNamespace(data_dir=Path(self.directory.name)), self.http, self.env_path
        )

    def test_pasted_token_is_stored_in_dotenv_and_never_returned(self):
        self.addon.configure("http://homeassistant.local:8123", "replacement.token_value-1")
        contents = self.env_path.read_text(encoding="utf-8")
        self.assertIn("GEMINI_API_KEY=keep-me", contents)
        self.assertIn("HOMEASSISTANT_TOKEN=replacement.token_value-1", contents)
        self.assertEqual(self.env_path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("replacement.token_value-1", json.dumps(self.addon.status()))
        self.assertEqual(os.environ["HOMEASSISTANT_TOKEN"], "replacement.token_value-1")

        cleared = self.addon.clear_token()
        self.assertFalse(cleared["has_token"])
        self.assertIn("GEMINI_API_KEY=keep-me", self.env_path.read_text(encoding="utf-8"))
        self.assertNotIn("HOMEASSISTANT_TOKEN", self.env_path.read_text(encoding="utf-8"))

    def test_connect_uses_environment_token_and_official_assist_endpoint(self):
        status = self.addon.connect()
        self.assertEqual(status["endpoint"], "http://homeassistant.local:8123/api/mcp/assist")
        self.assertTrue(status["has_token"])
        self.assertNotIn("secret-token", json.dumps(status))
        url, options = self.http.calls[0]
        self.assertEqual(url, status["endpoint"])
        self.assertEqual(options["headers"]["Authorization"], "Bearer secret-token")
        self.assertEqual(options["headers"]["Accept"], "application/json, text/event-stream")
        self.assertFalse(options["allow_redirects"])
        self.assertFalse((Path(self.directory.name) / "token").exists())

    def test_only_official_assist_tools_are_exposed_and_actions_are_reviewed(self):
        self.addon.connect()
        tools = self.addon.tool_specs()
        self.assertEqual(
            {tool.name for tool in tools},
            {"get_live_context", "intent_hass_turn_on", "light_hass_light_set"},
        )
        action = next(tool for tool in tools if tool.name == "intent_hass_turn_on")
        self.assertIn("pass the room as area", action.description)
        context = next(tool for tool in tools if tool.name == "get_live_context")
        self.assertIn("litter box", context.description)
        self.assertTrue(context.available_when("what is the cat litter status?"))
        self.assertTrue(context.available_when("Check the litterbox"))
        self.assertTrue(context.required_when("Check the litterbox"))
        self.assertTrue(context.available_when("Check the litter-box"))
        self.assertFalse(action.available_when("Check the litterbox"))
        self.assertTrue(context.available_when("what's Atlas's weight?"))
        self.assertFalse(action.available_when("what's Atlas's weight?"))
        self.assertTrue(context.available_when("do you see anything named poopcentral?"))
        self.assertFalse(action.available_when("do you see anything named poopcentral?"))
        self.assertIn("friendly name", context.handler({})["interpretation_guidance"])
        self.assertFalse(action.available_when("write a poem"))
        self.assertTrue(action.available_when("turn on the kitchen light"))
        before = len(self.http.calls)
        proposal = action.handler({"name": "Kitchen"})
        self.assertEqual(len(self.http.calls), before)
        self.assertEqual(proposal["status"], "awaiting_approval")
        self.addon.review(proposal["proposal_id"], True)
        self.assertEqual(self.http.calls[-1][1]["json"]["method"], "tools/call")

    def test_target_match_failure_tells_model_to_retry_with_area(self):
        self.addon.connect()
        self.addon.set_trusted(True)
        action = next(
            tool for tool in self.addon.tool_specs()
            if tool.name == "intent_hass_turn_on"
        )
        with self.assertRaisesRegex(MODULE.HomeAssistantError, "retry with the area argument"):
            action.handler({"name": "Missing light", "domain": ["light"]})

    def test_live_context_retries_without_partial_name_filter(self):
        self.addon.connect()
        context = next(
            tool for tool in self.addon.tool_specs()
            if tool.name == "get_live_context"
        )
        before = len(self.http.calls)
        result = context.handler({"name": "poopcentral", "domain": "sensor"})
        calls = self.http.calls[before:]
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1]["json"]["params"]["arguments"]["name"], "poopcentral")
        self.assertEqual(calls[1][1]["json"]["params"]["arguments"], {})
        self.assertIn("interpretation_guidance", result)

    def test_batch_entity_vocabulary_scans_persists_and_rewrites_names(self):
        self.addon.connect()
        scanned = self.addon.scan_entities()
        self.assertEqual(scanned["count"], 2)
        atlas = next(item for item in scanned["entities"] if item["name"] == "Atlas Weight")
        self.assertEqual(atlas["domain"], "sensor")
        self.assertEqual(atlas["home_assistant_aliases"], ["atlas weight"])

        saved = self.addon.save_entity_vocabulary([{
            "name": "Atlas Weight",
            "aliases": ["big guy", "Atlas's weight"],
            "note": "Atlas is the orange cat.",
        }])
        self.assertEqual(saved["vocabulary_count"], 1)
        context = next(
            tool for tool in self.addon.tool_specs()
            if tool.name == "get_live_context"
        )
        self.assertTrue(context.available_when("how is big guy doing?"))
        self.assertTrue(context.required_when("how is big guy doing?"))
        result = context.handler({"name": "big guy"})
        self.assertEqual(
            self.http.calls[-1][1]["json"]["params"]["arguments"]["name"],
            "Atlas Weight",
        )
        self.assertIn("Atlas is the orange cat", result["entity_vocabulary"])

        reloaded = MODULE.HomeAssistantAddon(
            SimpleNamespace(data_dir=Path(self.directory.name)), self.http, self.env_path
        )
        self.assertEqual(reloaded.status()["vocabulary_count"], 1)

    def test_vocabulary_rewrites_action_target_before_review(self):
        self.addon.connect()
        self.addon.save_entity_vocabulary([{
            "name": "Kitchen",
            "aliases": ["food room"],
            "note": "Kitchen ceiling lights.",
        }])
        action = next(
            tool for tool in self.addon.tool_specs()
            if tool.name == "intent_hass_turn_on"
        )
        proposal = action.handler({"name": "food room", "domain": ["light"]})
        pending = self.addon.status()["proposals"][0]
        self.assertEqual(pending["arguments"]["name"], "Kitchen")
        self.assertEqual(proposal["status"], "awaiting_approval")

    def test_vocabulary_rejects_an_alias_assigned_to_two_entities(self):
        with self.assertRaisesRegex(MODULE.HomeAssistantError, "unique everyday name"):
            self.addon.save_entity_vocabulary([
                {"name": "Atlas Weight", "aliases": ["Atlas"], "note": "weight"},
                {"name": "Atlas Visits", "aliases": ["Atlas"], "note": "visits"},
            ])

    def test_trust_petey_executes_requested_actions_and_persists(self):
        self.addon.connect()
        self.addon.set_trusted(True)
        action = next(
            tool for tool in self.addon.tool_specs()
            if tool.name == "intent_hass_turn_on"
        )
        before = len(self.http.calls)
        result = action.handler({"name": "Kitchen"})
        self.assertEqual(result["status"], "executed")
        self.assertEqual(len(self.http.calls), before + 1)
        reloaded = MODULE.HomeAssistantAddon(
            SimpleNamespace(data_dir=Path(self.directory.name)), self.http
        )
        self.assertTrue(reloaded.status()["trusted"])

    def test_missing_environment_token_is_actionable(self):
        with patch.dict(os.environ, {"HOMEASSISTANT_TOKEN": "", "HOME_ASSISTANT_TOKEN": ""}):
            addon = MODULE.HomeAssistantAddon(SimpleNamespace(data_dir=Path(self.directory.name)), self.http)
            with self.assertRaisesRegex(MODULE.HomeAssistantError, "Paste a Home Assistant token"):
                addon.connect()

    def test_sse_response_and_schema_are_bounded(self):
        response = Response({})
        response.headers = {"Content-Type": "text/event-stream"}
        response.text = 'event: message\ndata: {"jsonrpc":"2.0","id":7,"result":{"tools":[]}}\n\n'
        self.assertEqual(MODULE._parse_rpc_response(response, 7), {"tools": []})
        schema = MODULE._safe_schema({"type": "object", "$ref": "drop", "properties": {"name": {"type": "string", "$ref": "drop"}}})
        self.assertNotIn("$ref", schema)
        self.assertNotIn("$ref", schema["properties"]["name"])

    def test_manifest_routes_and_cross_origin_mutations(self):
        manifest = json.loads((ROOT / "petey-addon.json").read_text(encoding="utf-8"))
        record = AddonManager._validate_manifest(manifest, ROOT)
        self.assertEqual(record["id"], "home-assistant")
        app = Flask(__name__)
        context = SimpleNamespace(
            app=app, addon_id="home-assistant", addon_dir=ROOT,
            data_dir=Path(self.directory.name), state=MagicMock(), memory=MagicMock(),
            gallery=MagicMock(), runtime=MagicMock(), get_media_jobs=MagicMock(),
        )
        with patch.object(MODULE.requests, "post", side_effect=self.http):
            addon = MODULE.setup(context)
        client = app.test_client()
        status = client.get("/api/addons/home-assistant/status")
        self.assertEqual(status.status_code, 200)
        self.assertNotIn("secret-token", status.get_data(as_text=True))
        rejected = client.post(
            "/api/addons/home-assistant/connect", headers={"Origin": "https://evil.example"}
        )
        self.assertEqual(rejected.status_code, 403)
        self.assertTrue(addon.status()["connected"])
        entities = client.get("/api/addons/home-assistant/entities")
        self.assertEqual(entities.status_code, 200)
        self.assertEqual(entities.json["count"], 2)
        vocabulary = client.put(
            "/api/addons/home-assistant/entity-vocabulary",
            json={"entities": [{"name": "Atlas Weight", "aliases": ["Atlas"], "note": "cat"}]},
        )
        self.assertEqual(vocabulary.status_code, 200)
        self.assertEqual(vocabulary.json["vocabulary_count"], 1)


if __name__ == "__main__":
    unittest.main()
