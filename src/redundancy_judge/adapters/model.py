"""Loopback-only structured model calls and replayable private caching."""

from hashlib import sha256
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from ..common import JudgeFailure, atomic_json, canonical, identity, read_json


def object_schema(*, required=None, **properties):
    return {"type": "object", "properties": properties, "required": list(properties) if required is None else required,
            "additionalProperties": False}


TEXT = {"type": "string"}
MAYBE_TEXT = {"type": ["string", "null"]}
BOOLEAN = {"type": "boolean"}
NUMBER = {"type": "number"}
START = {"type": "integer", "minimum": 0}
END = {"type": "integer", "minimum": 1}
LEGACY_JUDGE_PROTOCOL_VERSION = "phase1.1.evidence_safety.v2"
JUDGE_PROTOCOL_VERSION = "phase1.2.lenient_quotes.v1"
RESPONSE_SCHEMAS = {
    "task_constraints": object_schema(uncertain=BOOLEAN,
        constraints={"type": "array", "items": object_schema(quote=TEXT, start={"type": "integer", "minimum": 0},
            end={"type": "integer", "minimum": 1})}),
    "evidence_update": object_schema(uncertain=BOOLEAN,
        updates={"type": "array", "items": object_schema(candidate=TEXT, constraint_id=TEXT,
            state={"enum": ["partially_supported", "supported", "conflicted", "refuted"]},
            quote=TEXT, resolves_conflict=BOOLEAN)}),
    "action_target": object_schema(candidate=MAYBE_TEXT, constraint_id=MAYBE_TEXT,
        gap_id=MAYBE_TEXT, intent=TEXT, confidence=NUMBER, evidence_basis={"type": "array", "items": TEXT}),
    "r1_verification": object_schema(confirmed=BOOLEAN, confidence=NUMBER, protection=MAYBE_TEXT),
    "final_candidate": object_schema(quote=MAYBE_TEXT),
}
LEGACY_RESPONSE_SCHEMAS = {
    **RESPONSE_SCHEMAS,
    "evidence_update": object_schema(uncertain=BOOLEAN,
        uncertainty_scope={"anyOf": [{"type": "null"}, object_schema(candidate=TEXT, constraint_id=TEXT,
            quote=TEXT, start=START, end=END)]},
        updates={"type": "array", "items": object_schema(candidate=TEXT, constraint_id=TEXT,
            state={"enum": ["partially_supported", "supported", "conflicted", "refuted", "unknown"]},
            quote=TEXT, start=START, end=END, resolves_conflict=BOOLEAN)}),
    "final_candidate": object_schema(quote=MAYBE_TEXT, start={**START, "type": ["integer", "null"]},
        end={**END, "type": ["integer", "null"]}, anchor=MAYBE_TEXT,
        anchor_start={**START, "type": ["integer", "null"]}, anchor_end={**END, "type": ["integer", "null"]}),
}


def uses_lenient_quotes(judge):
    return getattr(judge, "protocol_version", None) == JUDGE_PROTOCOL_VERSION


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ModelJudge:
    synthetic = False
    protocol_version = JUDGE_PROTOCOL_VERSION

    def _response(self, kind, response):
        if not isinstance(response, dict):
            raise JudgeFailure("judge output is not a JSON object")
        if not self.response_schemas[kind]["properties"].keys() >= response.keys():
            raise JudgeFailure("judge output contains unknown fields")
        if kind in {"evidence_update", "final_candidate"} and not set(self.response_schemas[kind]["required"]) <= response.keys():
            raise JudgeFailure("versioned judge response is missing required fields")
        return response

    def __init__(self, config, prompt_dir, cache_dir, freeze, *, replay_only=False):
        url = config["url"].rstrip("/")
        parsed = urlsplit(url)
        if (parsed.scheme != "http" or not parsed.hostname or
            not ipaddress.ip_address(parsed.hostname).is_loopback or parsed.username or
            parsed.password or parsed.query or parsed.fragment):
            raise ValueError("judge URL must be HTTP on a numeric loopback address")
        self.endpoint = url + "/chat/completions"
        self.models_endpoint = url + "/models"
        self.name = config["model"]
        self.timeout = config.get("timeout", 90)
        self.max_tokens = config.get("max_tokens", 4096)
        self.prompts = {p.stem: p.read_text(encoding="utf-8") for p in Path(prompt_dir).glob("*.md")}
        self.prompt_sha256 = identity(self.prompts)
        self.cache = Path(cache_dir)
        self.freeze = freeze
        self.replay_only = replay_only
        historical = replay_only and freeze.get("judge_protocol_version") == LEGACY_JUDGE_PROTOCOL_VERSION
        self.protocol_version = LEGACY_JUDGE_PROTOCOL_VERSION if historical else JUDGE_PROTOCOL_VERSION
        self.response_schemas = LEGACY_RESPONSE_SCHEMAS if historical else RESPONSE_SCHEMAS
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def check_service(self):
        try:
            with self.opener.open(self.models_endpoint, timeout=min(self.timeout, 10)) as stream:
                payload = json.loads(stream.read(1_000_000))
            if self.name not in {entry["id"] for entry in payload["data"]}:
                raise JudgeFailure("expected local model is not served")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise JudgeFailure(f"local model availability check failed ({type(exc).__name__})") from exc

    def ask(self, kind, payload):
        prompt = self.prompts[kind]
        body = {"model": self.name, "temperature": 0, "max_tokens": self.max_tokens,
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": kind, "strict": True, "schema": self.response_schemas[kind]}},
                "reasoning_effort": "low",
                "messages": [{"role": "system", "content": prompt},
                             {"role": "user", "content": canonical(payload)}]}
        key = identity([self.protocol_version, self.freeze, self.prompt_sha256, body])
        path = self.cache / key[:2] / (key + ".json")
        if path.exists():
            receipt = read_json(path)
            if receipt["cache_key"] != key or receipt.get("protocol_version") != self.protocol_version:
                raise JudgeFailure("cache identity mismatch")
            if "response" in receipt:
                return self._response(kind, receipt["response"])
            raise JudgeFailure(receipt["failure"])
        if self.replay_only:
            raise JudgeFailure("replay cache entry is missing")
        request = Request(self.endpoint, canonical(body).encode(), {"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=self.timeout) as stream:
                raw = stream.read(4_000_001)
            if len(raw) > 4_000_000:
                raise JudgeFailure("judge response exceeds size limit")
            envelope = json.loads(raw)
            if envelope.get("model") != self.name:
                raise JudgeFailure("judge model identity mismatch")
            choice = envelope["choices"][0]
            if choice["finish_reason"] != "stop":
                raise JudgeFailure("judge generation did not finish")
            if choice["message"].get("tool_calls"):
                raise JudgeFailure("judge attempted a tool call")
            response = self._response(kind, json.loads(choice["message"]["content"], parse_constant=lambda v: float(v)))
            canonical(response)
        except JudgeFailure as exc:
            atomic_json(path, {"cache_key": key, "protocol_version": self.protocol_version, "failure": str(exc)})
            raise
        except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
            message = f"judge transport or JSON failure ({type(exc).__name__})"
            atomic_json(path, {"cache_key": key, "protocol_version": self.protocol_version, "failure": message})
            raise JudgeFailure(message) from exc
        atomic_json(path, {"cache_key": key, "protocol_version": self.protocol_version,
                           "response": response, "usage": envelope.get("usage"),
                           "response_sha256": sha256(raw).hexdigest()})
        return response


class SyntheticJudge:
    synthetic = True
    protocol_version = JUDGE_PROTOCOL_VERSION
    name = "synthetic-fixture"
    prompt_sha256 = "synthetic"

    def ask(self, kind, payload):
        if kind == "task_constraints":
            question = payload["question"]
            return {"constraints": [{"quote": question, "start": 0, "end": len(question)}],
                    "uncertain": False}
        if kind == "action_target":
            return {"intent": "unknown", "confidence": 0, "candidate": None, "constraint_id": None,
                    "gap_id": None, "evidence_basis": []}
        if kind == "evidence_update":
            return {"updates": [], "uncertain": False}
        if kind == "r1_verification":
            return {"confirmed": False, "confidence": 1, "protection": None}
        if kind == "final_candidate":
            return dict.fromkeys(RESPONSE_SCHEMAS[kind]["required"])
        raise JudgeFailure("unsupported fixture prompt")
