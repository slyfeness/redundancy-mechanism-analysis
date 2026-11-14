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
RESPONSE_SCHEMAS = {
    "task_constraints": object_schema(uncertain=BOOLEAN,
        constraints={"type": "array", "items": object_schema(quote=TEXT, start={"type": "integer", "minimum": 0},
            end={"type": "integer", "minimum": 1})}),
    "evidence_update": object_schema(uncertain=BOOLEAN,
        updates={"type": "array", "items": object_schema(candidate=TEXT, constraint_id=TEXT,
            state=TEXT, quote=TEXT, start={"type": "integer", "minimum": 0},
            end={"type": "integer", "minimum": 1}, resolves_conflict=BOOLEAN)}),
    "action_target": object_schema(candidate=MAYBE_TEXT, constraint_id=MAYBE_TEXT,
        gap_id=MAYBE_TEXT, intent=TEXT, confidence=NUMBER, evidence_basis={"type": "array", "items": TEXT}),
    "r1_verification": object_schema(confirmed=BOOLEAN, confidence=NUMBER, protection=MAYBE_TEXT),
    "final_candidate": object_schema(quote=MAYBE_TEXT, start={"type": ["integer", "null"], "minimum": 0},
        end={"type": ["integer", "null"], "minimum": 1}, anchor=MAYBE_TEXT),
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ModelJudge:
    synthetic = False

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
                    "name": kind, "strict": True, "schema": RESPONSE_SCHEMAS[kind]}},
                "reasoning_effort": "low",
                "messages": [{"role": "system", "content": prompt},
                             {"role": "user", "content": canonical(payload)}]}
        key = identity([self.freeze, self.prompt_sha256, body])
        path = self.cache / key[:2] / (key + ".json")
        if path.exists():
            receipt = read_json(path)
            if receipt["cache_key"] != key:
                raise JudgeFailure("cache identity mismatch")
            if "response" in receipt:
                return receipt["response"]
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
            response = json.loads(choice["message"]["content"], parse_constant=lambda v: float(v))
            if not isinstance(response, dict):
                raise JudgeFailure("judge output is not a JSON object")
            canonical(response)
        except JudgeFailure as exc:
            atomic_json(path, {"cache_key": key, "failure": str(exc)})
            raise
        except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
            message = f"judge transport or JSON failure ({type(exc).__name__})"
            atomic_json(path, {"cache_key": key, "failure": message})
            raise JudgeFailure(message) from exc
        atomic_json(path, {"cache_key": key, "response": response, "usage": envelope.get("usage"),
                           "response_sha256": sha256(raw).hexdigest()})
        return response


class SyntheticJudge:
    synthetic = True
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
            return {"quote": None, "start": None, "end": None, "anchor": None}
        raise JudgeFailure("unsupported fixture prompt")
