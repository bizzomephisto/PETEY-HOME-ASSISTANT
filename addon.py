"""Home Assistant Streamable HTTP MCP add-on for PETEY."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit, urlunsplit
import uuid

from flask import jsonify, request
import requests

from petey.tools.registry import ToolSpec


MAX_RESULT_CHARS = 60_000
MAX_PROPOSALS = 12
MAX_VOCABULARY_ENTRIES = 300
PROPOSAL_LIFETIME = 10 * 60
TOKEN_ENV_NAMES = ("HOMEASSISTANT_TOKEN", "HOME_ASSISTANT_TOKEN")
URL_ENV_NAMES = ("HOMEASSISTANT_URL", "HOME_ASSISTANT_URL")
DEFAULT_URL = "http://homeassistant.local:8123"
LIVE_CONTEXT_TOOL = "homeassistant__GetLiveContext"
ACTION_TOOL_NAME = re.compile(r"^(?:[a-z0-9_]+__)?Hass[A-Za-z0-9_]+$")
HOME_INTENT = re.compile(
    r"\b(home assistant|smart home|device|devices|light|lights|lamp|switch|fan|"
    r"thermostat|climate|temperature|lock|door|garage|blind|blinds|cover|curtain|"
    r"media player|speaker|volume|humidifier|timer|shopping list|todo|to-do|"
    r"broadcast|scene|vacuum|mower|litter|litter box|cat|pet|waste drawer|sensor|"
    r"battery|status|level|weight|weigh|weighs|visit|visits|poop|poops|hopper)\b",
    re.IGNORECASE,
)
ACTION_INTENT = re.compile(
    r"\b(turn|switch|set|start|stop|clean|return|broadcast|add|complete|remove|"
    r"cancel|open|close|lock|unlock|dim|brighten)\b",
    re.IGNORECASE,
)
ENTITY_LOOKUP_INTENT = re.compile(
    r"\b(?:(?:do|can|could) you (?:see|find|access|recognize)|"
    r"(?:anything|something) (?:named|called)|"
    r"(?:find|look up|check) (?:an? |the )?(?:entity|device|sensor))\b",
    re.IGNORECASE,
)
LIVE_CONTEXT_GUIDANCE = (
    "Use each entity's friendly name as its device type. The Home Assistant domain "
    "is an implementation and service category: for example, an entity named "
    "'Litter box' may use the vacuum domain but should still be described as a "
    "litter box. Custom names may be only part of a longer friendly name; use an "
    "unfiltered live-context result to match them instead of claiming they are missing."
)
ENV_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


class HomeAssistantError(ValueError):
    """Safe error text suitable for PETEY's local interface."""


def _env_first(names: tuple[str, ...]) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _project_env_path() -> Path:
    import petey

    return Path(petey.__file__).resolve().parent.parent / ".env"


def _write_env_value(path: Path, key: str, value: str) -> None:
    """Atomically update one dotenv value without exposing or rewriting others."""
    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""
    except OSError as exc:
        raise HomeAssistantError("PETEY's .env file could not be read.") from exc
    lines = existing.splitlines(keepends=True)
    replacement = f"{key}={value}\n"
    updated = []
    replaced = False
    for line in lines:
        match = ENV_ASSIGNMENT.match(line)
        if match and match.group(1) == key:
            if not replaced:
                updated.append(replacement)
                replaced = True
            continue
        updated.append(line)
    if not replaced:
        if updated and not updated[-1].endswith(("\n", "\r")):
            updated[-1] += "\n"
        updated.append(replacement)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".home-assistant-tmp")
    try:
        temporary.write_text("".join(updated), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise HomeAssistantError("HOMEASSISTANT_TOKEN could not be saved to PETEY's .env file.") from exc


def _remove_env_values(path: Path, keys: tuple[str, ...]) -> None:
    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    except OSError as exc:
        raise HomeAssistantError("PETEY's .env file could not be read.") from exc
    lines = [
        line for line in existing.splitlines(keepends=True)
        if not ((match := ENV_ASSIGNMENT.match(line)) and match.group(1) in keys)
    ]
    temporary = path.with_name(path.name + ".home-assistant-tmp")
    try:
        temporary.write_text("".join(lines), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise HomeAssistantError("HOMEASSISTANT_TOKEN could not be removed from PETEY's .env file.") from exc


def _normalize_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise HomeAssistantError("Enter your Home Assistant address.")
    if "://" not in text:
        text = "http://" + text
    parsed = urlsplit(text)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise HomeAssistantError(
            "Enter an HTTP or HTTPS Home Assistant address without credentials or a query string."
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise HomeAssistantError("The Home Assistant address has an invalid port.") from exc
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port else host
    path = parsed.path.rstrip("/")
    for suffix in ("/api/mcp/assist", "/api/mcp"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urlunsplit((parsed.scheme, netloc, path, "", "")).rstrip("/")


def _safe_schema(value: object, depth: int = 0) -> dict:
    """Bound and sanitize an upstream JSON Schema before model exposure."""
    if not isinstance(value, dict) or depth > 7:
        return {}
    result = {}
    for key in (
        "type", "description", "default", "minimum", "maximum", "minLength",
        "maxLength", "minItems", "maxItems",
    ):
        item = value.get(key)
        if isinstance(item, (str, int, float, bool)):
            result[key] = item
    if isinstance(value.get("enum"), list):
        result["enum"] = value["enum"][:100]
    if isinstance(value.get("required"), list):
        result["required"] = [str(item) for item in value["required"][:40]]
    if isinstance(value.get("properties"), dict):
        result["properties"] = {
            str(key): _safe_schema(item, depth + 1)
            for key, item in list(value["properties"].items())[:40]
            if isinstance(item, dict)
        }
    if isinstance(value.get("items"), dict):
        result["items"] = _safe_schema(value["items"], depth + 1)
    for key in ("anyOf", "oneOf"):
        if isinstance(value.get(key), list):
            result[key] = [
                _safe_schema(item, depth + 1)
                for item in value[key][:8]
                if isinstance(item, dict)
            ]
    result.setdefault("type", "object" if "properties" in result else "string")
    if result["type"] == "object":
        result.setdefault("properties", {})
    return result


def _local_tool_name(upstream: str) -> str:
    name = upstream.removeprefix("homeassistant__")
    name = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    name = re.sub(r"[^a-z0-9_]+", "_", name)
    return re.sub(r"_+", "_", name).strip("_")[:64]


def _is_action_tool(name: object) -> bool:
    """Recognize Home Assistant Assist actions across component namespaces."""
    return bool(ACTION_TOOL_NAME.fullmatch(str(name or "")))


def _tool_failure_message(result: dict) -> str:
    """Turn MCP tool failures into safe, useful feedback for the model and user."""
    content = result.get("content")
    messages = [
        str(item.get("text") or "").strip()
        for item in content if isinstance(item, dict)
    ] if isinstance(content, list) else []
    detail = " ".join(item for item in messages if item)
    if "MatchFailedError" in detail or "no_match_reason" in detail:
        return (
            "Home Assistant could not match that target. For all lights in a room or "
            "area, retry with the area argument and domain=['light']; use name only "
            "for one exact exposed entity."
        )
    if detail:
        detail = re.sub(r"\s+", " ", detail)[:500]
        return f"Home Assistant rejected the action: {detail}"
    return "Home Assistant could not complete that request."


def _action_target_guidance(upstream: str) -> str:
    if upstream in {"intent__HassTurnOn", "intent__HassTurnOff"}:
        return (
            "For a group request such as 'living room lights' or 'outside lights', "
            "pass the room as area and pass domain=['light']. Use name only for one "
            "exact entity name."
        )
    return ""


def _normalized_phrase(value: object) -> str:
    text = str(value or "").casefold().replace("’", "'")
    return re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).strip()


def _live_context_text(result: dict) -> str:
    """Extract Home Assistant's text context from PETEY's bounded call result."""
    try:
        content = json.loads(str(result.get("result") or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    chunks = []
    for item in content if isinstance(content, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        text = item["text"]
        try:
            payload = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            chunks.append(text)
            continue
        if isinstance(payload, dict) and isinstance(payload.get("result"), str):
            chunks.append(payload["result"])
    return "\n".join(chunks)


def _parse_live_entities(text: str) -> list[dict]:
    """Parse the stable, line-oriented entity summary returned by Assist."""
    entities = {}
    for block in re.split(r"(?m)^- names:\s*", str(text or ""))[1:]:
        lines = block.splitlines()
        names = [item.strip() for item in lines[0].split(",") if item.strip()]
        if not names:
            continue
        fields = {}
        for line in lines[1:]:
            match = re.match(r"^  ([a-z_]+):\s*(.*)$", line)
            if match:
                fields[match.group(1)] = match.group(2).strip().strip("'\"")
        name = names[0][:200]
        domain = str(fields.get("domain") or "")[:80]
        key = (name.casefold(), domain.casefold())
        entities[key] = {
            "name": name,
            "home_assistant_aliases": names[1:20],
            "domain": domain,
            "area": str(fields.get("areas") or "")[:120],
            "state": str(fields.get("state") or "")[:200],
        }
    return sorted(entities.values(), key=lambda item: (item["name"].casefold(), item["domain"]))


def _validated_vocabulary(value: object) -> dict[str, dict]:
    if not isinstance(value, list):
        return {}
    result = {}
    for item in value[:MAX_VOCABULARY_ENTRIES]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:200]
        if not name:
            continue
        aliases = []
        raw_aliases = item.get("aliases")
        if isinstance(raw_aliases, list):
            for alias in raw_aliases[:12]:
                alias = str(alias or "").strip()[:120]
                if alias and _normalized_phrase(alias) not in {
                    _normalized_phrase(existing) for existing in aliases
                }:
                    aliases.append(alias)
        note = str(item.get("note") or "").strip()[:400]
        if aliases or note:
            result[name] = {"name": name, "aliases": aliases, "note": note}
    return result


def _parse_rpc_response(response, request_id: int) -> dict:
    """Parse either JSON or Streamable HTTP's event-stream response form."""
    content_type = str(response.headers.get("Content-Type") or "").lower()
    try:
        if "text/event-stream" in content_type:
            messages = []
            for line in response.text.splitlines():
                if line.startswith("data:"):
                    messages.append(json.loads(line[5:].strip()))
            message = next(
                (item for item in messages if isinstance(item, dict) and item.get("id") == request_id),
                None,
            )
        else:
            message = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise HomeAssistantError("Home Assistant returned an invalid MCP response.") from exc
    if not isinstance(message, dict) or message.get("id") != request_id:
        raise HomeAssistantError("Home Assistant returned an unexpected MCP response.")
    if isinstance(message.get("error"), dict):
        detail = str(message["error"].get("message") or "MCP request failed.")[:300]
        raise HomeAssistantError(f"Home Assistant MCP: {detail}")
    result = message.get("result")
    if not isinstance(result, dict):
        raise HomeAssistantError("Home Assistant returned an empty MCP result.")
    return result


class HomeAssistantAddon:
    def __init__(self, context, http_post=None, env_path=None):
        self.data_dir = Path(context.data_dir)
        self.config_path = self.data_dir / "config.json"
        self.env_path = Path(env_path) if env_path else _project_env_path()
        self._http_post = http_post or requests.post
        self._request_id = 0
        self._connected = False
        self._tools: list[dict] = []
        self._proposals: dict[str, dict] = {}
        self._error = ""
        self._lock = threading.RLock()
        self._base_url = _normalize_url(_env_first(URL_ENV_NAMES) or DEFAULT_URL)
        self._trusted = False
        self._entity_vocabulary: dict[str, dict] = {}
        self._load_config()

    def _load_config(self) -> None:
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
            if not _env_first(URL_ENV_NAMES):
                self._base_url = _normalize_url(payload.get("base_url") or DEFAULT_URL)
            self._trusted = payload.get("trusted") is True
            self._entity_vocabulary = _validated_vocabulary(payload.get("entity_vocabulary"))
        except FileNotFoundError:
            return
        except (OSError, ValueError, json.JSONDecodeError):
            self._error = "Saved Home Assistant settings could not be read."

    def _write_config(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({
                "base_url": self._base_url,
                "trusted": self._trusted,
                "entity_vocabulary": list(self._entity_vocabulary.values()),
            }, indent=2),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        temporary.replace(self.config_path)

    def _token(self) -> str:
        return _env_first(TOKEN_ENV_NAMES)

    @property
    def endpoint(self) -> str:
        return self._base_url + "/api/mcp/assist"

    def save_token(self, token: object) -> None:
        token_text = str(token or "").strip()
        if not token_text:
            return
        if len(token_text) > 4096 or not re.fullmatch(r"[A-Za-z0-9._~-]+", token_text):
            raise HomeAssistantError("The Home Assistant token has an invalid format.")
        _write_env_value(self.env_path, "HOMEASSISTANT_TOKEN", token_text)
        os.environ["HOMEASSISTANT_TOKEN"] = token_text
        os.environ.pop("HOME_ASSISTANT_TOKEN", None)

    def clear_token(self) -> dict:
        with self._lock:
            _remove_env_values(self.env_path, TOKEN_ENV_NAMES)
            for name in TOKEN_ENV_NAMES:
                os.environ.pop(name, None)
            self.disconnect()
            return self.status()

    def configure(self, base_url: object, token: object = "") -> dict:
        with self._lock:
            if _env_first(URL_ENV_NAMES):
                self._base_url = _normalize_url(_env_first(URL_ENV_NAMES))
            else:
                self._base_url = _normalize_url(base_url)
            self.save_token(token)
            self._write_config()
            self.disconnect()
            return self.status()

    def set_trusted(self, trusted: object) -> dict:
        if type(trusted) is not bool:
            raise HomeAssistantError("Trust PETEY must be true or false.")
        with self._lock:
            self._trusted = trusted
            if trusted:
                self._proposals.clear()
            self._write_config()
            return self.status()

    def save_entity_vocabulary(self, entries: object) -> dict:
        if not isinstance(entries, list):
            raise HomeAssistantError("Entity vocabulary must be a list.")
        if len(entries) > MAX_VOCABULARY_ENTRIES:
            raise HomeAssistantError(
                f"Entity vocabulary is limited to {MAX_VOCABULARY_ENTRIES} entries."
            )
        vocabulary = _validated_vocabulary(entries)
        phrases = {}
        for item in vocabulary.values():
            for phrase in [item["name"], *item["aliases"]]:
                normalized = _normalized_phrase(phrase)
                previous = phrases.get(normalized)
                if normalized and previous and previous != item["name"]:
                    raise HomeAssistantError(
                        f'“{phrase}” is assigned to both “{previous}” and “{item["name"]}”. '
                        "Use a unique everyday name for each entity."
                    )
                phrases[normalized] = item["name"]
        with self._lock:
            self._entity_vocabulary = vocabulary
            self._write_config()
            return {
                "status": "saved",
                "vocabulary_count": len(self._entity_vocabulary),
            }

    def _vocabulary_matches(self, message: object) -> bool:
        normalized = f" {_normalized_phrase(message)} "
        for item in self._entity_vocabulary.values():
            for phrase in [item["name"], *item["aliases"]]:
                alias = _normalized_phrase(phrase)
                if len(alias) >= 2 and f" {alias} " in normalized:
                    return True
        return False

    def _canonical_name(self, value: object) -> str:
        normalized = _normalized_phrase(value)
        if not normalized:
            return str(value or "")
        for item in self._entity_vocabulary.values():
            phrases = [item["name"], *item["aliases"]]
            if any(_normalized_phrase(phrase) == normalized for phrase in phrases):
                return item["name"]
        return str(value or "")

    def _rewrite_arguments(self, arguments: dict) -> dict:
        rewritten = dict(arguments) if isinstance(arguments, dict) else {}
        if isinstance(rewritten.get("name"), str):
            rewritten["name"] = self._canonical_name(rewritten["name"])
        return rewritten

    def _vocabulary_guidance(self) -> str:
        lines = []
        for item in self._entity_vocabulary.values():
            aliases = ", ".join(item["aliases"])
            meaning = f"; meaning: {item['note']}" if item["note"] else ""
            lines.append(f"{aliases} => {item['name']}{meaning}")
        if not lines:
            return ""
        return "PETEY entity vocabulary:\n" + "\n".join(lines)[:12_000]

    def scan_entities(self) -> dict:
        with self._lock:
            result = self._call(LIVE_CONTEXT_TOOL, {})
            entities = _parse_live_entities(_live_context_text(result))
            for entity in entities:
                saved = self._entity_vocabulary.get(entity["name"], {})
                entity["aliases"] = list(saved.get("aliases") or [])
                entity["note"] = str(saved.get("note") or "")
                entity["available"] = True
            current_names = {item["name"] for item in entities}
            for name, saved in self._entity_vocabulary.items():
                if name not in current_names:
                    entities.append({
                        "name": name, "home_assistant_aliases": [], "domain": "",
                        "area": "", "state": "", "aliases": list(saved["aliases"]),
                        "note": saved["note"], "available": False,
                    })
            return {"entities": entities, "count": len(entities)}

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        token = self._token()
        if not token:
            raise HomeAssistantError(
                "Paste a Home Assistant token in PETEY and choose Save & connect."
            )
        self._request_id += 1
        request_id = self._request_id
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        try:
            response = self._http_post(
                self.endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                timeout=(5, 65),
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise HomeAssistantError(
                "Could not reach Home Assistant. Check its address and local network connection."
            ) from exc
        if response.status_code in {401, 403}:
            raise HomeAssistantError("Home Assistant rejected HOMEASSISTANT_TOKEN.")
        if 300 <= response.status_code < 400:
            raise HomeAssistantError(
                "Home Assistant redirected the MCP request. Use its direct address."
            )
        if response.status_code != 200:
            raise HomeAssistantError(
                f"Home Assistant MCP returned HTTP {response.status_code}."
            )
        return _parse_rpc_response(response, request_id)

    def connect(self) -> dict:
        with self._lock:
            try:
                advertised = self._rpc("tools/list", {}).get("tools", [])
                tools = [item for item in advertised if isinstance(item, dict)]
                approved = [
                    item for item in tools
                    if item.get("name") == LIVE_CONTEXT_TOOL
                    or _is_action_tool(item.get("name"))
                ]
                if not approved:
                    raise HomeAssistantError(
                        "Home Assistant exposed no supported Assist tools. Check the MCP Server integration and exposed entities."
                    )
                self._tools = approved
                self._connected = True
                self._error = ""
            except HomeAssistantError as exc:
                self._connected = False
                self._tools = []
                self._error = str(exc)
                raise
            return self.status()

    def disconnect(self) -> dict:
        with self._lock:
            self._connected = False
            self._tools = []
            self._proposals.clear()
            return self.status()

    def _expire(self) -> None:
        now = time.time()
        self._proposals = {
            key: item for key, item in self._proposals.items() if item["expires_at"] > now
        }

    def status(self) -> dict:
        with self._lock:
            self._expire()
            actions = [
                item for item in self._tools
                if _is_action_tool(item.get("name"))
            ]
            return {
                "base_url": self._base_url,
                "endpoint": self.endpoint,
                "has_token": bool(self._token()),
                "connected": self._connected,
                "trusted": self._trusted,
                "tool_count": len(self._tools),
                "action_count": len(actions),
                "vocabulary_count": len(self._entity_vocabulary),
                "error": self._error,
                "proposals": [
                    {
                        "id": item["id"],
                        "tool": item["local_name"],
                        "summary": item["summary"],
                        "arguments": item["arguments"],
                        "expires_at": item["expires_at"],
                    }
                    for item in self._proposals.values()
                ],
            }

    def _call(self, tool: str, arguments: dict) -> dict:
        if not self._connected:
            raise HomeAssistantError("Connect Home Assistant first.")
        result = self._rpc("tools/call", {"name": tool, "arguments": arguments})
        if result.get("isError"):
            raise HomeAssistantError(_tool_failure_message(result))
        text = json.dumps(result.get("content", []), ensure_ascii=False)
        return {"result": text[:MAX_RESULT_CHARS], "truncated": len(text) > MAX_RESULT_CHARS}

    def call_read(self, tool: str, arguments: dict) -> dict:
        with self._lock:
            arguments = self._rewrite_arguments(arguments)
            result = self._call(tool, arguments)
            if tool == LIVE_CONTEXT_TOOL:
                # Assist name filters require an exact exposed name. Models often
                # supply a household nickname such as "poopcentral" even though
                # the exposed entities are "poopcentral Litter level" and similar.
                # Fall back to the bounded full context rather than reporting a
                # false absence. This remains inside the official Assist MCP API.
                if arguments and "No exposed entities matched" in str(result.get("result") or ""):
                    result = self._call(tool, {})
                result["interpretation_guidance"] = LIVE_CONTEXT_GUIDANCE
                vocabulary = self._vocabulary_guidance()
                if vocabulary:
                    result["entity_vocabulary"] = vocabulary
            return result

    def request_action(self, tool: str, local_name: str, arguments: dict) -> dict:
        with self._lock:
            if not self._connected or not _is_action_tool(tool):
                raise HomeAssistantError("That Home Assistant action is unavailable.")
            arguments = self._rewrite_arguments(arguments)
            if self._trusted:
                return {
                    **self._call(tool, arguments),
                    "status": "executed",
                    "message": "Trusted Home Assistant action executed.",
                }
            self._expire()
            if len(self._proposals) >= MAX_PROPOSALS:
                raise HomeAssistantError("Review existing Home Assistant proposals first.")
            proposal_id = uuid.uuid4().hex
            self._proposals[proposal_id] = {
                "id": proposal_id,
                "tool": tool,
                "local_name": local_name,
                "summary": local_name.replace("_", " ").capitalize(),
                "arguments": arguments,
                "expires_at": time.time() + PROPOSAL_LIFETIME,
            }
            return {
                "proposal_id": proposal_id,
                "status": "awaiting_approval",
                "message": (
                    "The action has not run. Review it in PETEY's Home Assistant panel "
                    "within ten minutes."
                ),
            }

    def review(self, proposal_id: str, approve: bool) -> dict:
        with self._lock:
            self._expire()
            item = self._proposals.pop(proposal_id, None)
            if item is None:
                raise HomeAssistantError("The proposal is missing or expired.")
            if not approve:
                return {"status": "rejected"}
            return self._call(item["tool"], item["arguments"])

    def tool_specs(self) -> list[ToolSpec]:
        with self._lock:
            if not self._connected:
                return []
            action_available = lambda message: bool(
                (HOME_INTENT.search(message) or self._vocabulary_matches(message))
                and ACTION_INTENT.search(message)
            )
            context_available = lambda message: bool(
                HOME_INTENT.search(message) or ENTITY_LOOKUP_INTENT.search(message)
                or self._vocabulary_matches(message)
            )
            specs = []
            used = set()
            for item in self._tools:
                upstream = str(item.get("name") or "")
                local_name = _local_tool_name(upstream)
                if not local_name or local_name in used:
                    continue
                used.add(local_name)
                schema = _safe_schema(
                    item.get("inputSchema") or {"type": "object", "properties": {}}
                )
                description = str(item.get("description") or local_name.replace("_", " "))[:1200]
                if upstream == LIVE_CONTEXT_TOOL:
                    description = f"{description} {LIVE_CONTEXT_GUIDANCE}"
                    handler = lambda arguments, selected=upstream: self.call_read(selected, arguments)
                    available = context_available
                else:
                    policy = (
                        "This action runs immediately because Trust PETEY is enabled."
                        if self._trusted
                        else "This action creates a proposal and does not run until approved."
                    )
                    guidance = _action_target_guidance(upstream)
                    description = " ".join(part for part in (description, guidance, policy) if part)
                    handler = lambda arguments, selected=upstream, name=local_name: self.request_action(
                        selected, name, arguments
                    )
                    available = action_available
                specs.append(
                    ToolSpec(
                        name=local_name,
                        description=description,
                        parameters=schema,
                        handler=handler,
                        available_when=available,
                        required_when=(context_available if upstream == LIVE_CONTEXT_TOOL else action_available),
                    )
                )
            return specs

    def close(self) -> None:
        self.disconnect()


def setup(context):
    addon = HomeAssistantAddon(context)
    prefix = f"/api/addons/{context.addon_id}"
    endpoint_prefix = f"addon_{context.addon_id.replace('-', '_')}"

    def safely(operation):
        try:
            return jsonify(operation())
        except HomeAssistantError as exc:
            return jsonify({"error": str(exc)}), 400

    def same_origin():
        origin = request.headers.get("Origin")
        return not origin or origin == request.host_url.rstrip("/")

    def mutation(operation):
        if not same_origin():
            return jsonify({"error": "Home Assistant must be managed from PETEY."}), 403
        return safely(operation)

    def update_config():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Expected a JSON object."}), 400
        return mutation(lambda: addon.configure(payload.get("base_url"), payload.get("token", "")))

    def update_trust():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Expected a JSON object."}), 400
        return mutation(lambda: addon.set_trusted(payload.get("trusted")))

    def update_vocabulary():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Expected a JSON object."}), 400
        return mutation(lambda: addon.save_entity_vocabulary(payload.get("entities")))

    def review():
        payload = request.get_json(silent=True)
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("id"), str)
            or type(payload.get("approve")) is not bool
        ):
            return jsonify({"error": "Expected a proposal id and boolean approve value."}), 400
        return mutation(lambda: addon.review(payload["id"], payload["approve"]))

    routes = (
        ("/status", "status", ["GET"], lambda: jsonify(addon.status())),
        ("/config", "config", ["PUT"], update_config),
        ("/trust", "trust", ["PUT"], update_trust),
        ("/token", "token", ["DELETE"], lambda: mutation(addon.clear_token)),
        ("/connect", "connect", ["POST"], lambda: mutation(addon.connect)),
        ("/disconnect", "disconnect", ["POST"], lambda: mutation(addon.disconnect)),
        ("/entities", "entities", ["GET"], lambda: safely(addon.scan_entities)),
        ("/entity-vocabulary", "entity_vocabulary", ["PUT"], update_vocabulary),
        ("/review", "review", ["POST"], review),
    )
    for path, name, methods, handler in routes:
        context.app.add_url_rule(
            prefix + path,
            endpoint=f"{endpoint_prefix}_{name}",
            view_func=handler,
            methods=methods,
        )

    if addon.status()["has_token"]:
        try:
            addon.connect()
        except HomeAssistantError:
            pass
    return addon
