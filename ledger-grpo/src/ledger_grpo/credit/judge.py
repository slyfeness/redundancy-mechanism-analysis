"""Exact recorded Judge requests, and an explicitly enabled HTTP backend.

Constructing an HTTP client never connects. Replay has no network fallback.
"""
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit
import http.client
import json


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def request_body(prompt, payload, cfg):
    # Preserve v13.4 field order and user-message bytes, including Unicode.
    return {**{key: cfg[key] for key in ("model", "temperature", "seed", "reasoning_effort", "max_tokens")},
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": encode(payload)}]}


def request_key(request):
    # Only outer dictionary ordering is irrelevant. Message content is exact.
    return json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def q2_cache_key(prompt, payload, cfg, conditions_version):
    """Hash all rendered inputs plus the explicit condition-schema version."""
    request = request_body(prompt, payload, cfg)
    content = {"request": request, "conditions_version": conditions_version,
               "prompt_sha256": sha256(prompt.encode("utf-8")).hexdigest(),
               "documents_sha256": sha256(encode(payload.get("返回句子", [])).encode("utf-8")).hexdigest()}
    return sha256(request_key(content).encode("utf-8")).hexdigest()


class ReplayMissError(LookupError):
    pass


class ReplayJudgeClient:
    """FIFO receipts for each complete request; repeated retries remain distinct."""
    def __init__(self, receipts=()):
        self._receipts = defaultdict(list)
        self._positions = defaultdict(int)
        self.requests = 0
        self.online_requests = 0
        self.missing_requests = []
        for receipt in receipts:
            self._receipts[request_key(receipt["request"])].append(deepcopy(receipt))

    @classmethod
    def from_state_files(cls, paths):
        from .pipeline import calls_of
        receipts = []
        for path in paths:
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                for _, call in calls_of(json.loads(line)):
                    receipts.extend(attempt["receipt"] for attempt in call["attempts"])
        return cls(receipts)

    def complete(self, request):
        key = request_key(request)
        position = self._positions[key]
        self.requests += 1
        if key not in self._receipts or position >= len(self._receipts[key]):
            self.missing_requests.append(deepcopy(request))
            raise ReplayMissError("No unused receipt for exact request " + sha256(key.encode()).hexdigest())
        receipt = deepcopy(self._receipts[key][position])
        self._positions[key] += 1
        return receipt

    def __call__(self, folder, key, prompt, payload, cfg, max_retries=0):
        if max_retries != 0:
            raise ValueError("The frozen checked pipeline owns retries")
        receipt = self.complete(request_body(prompt, payload, cfg))
        return receipt.get("parsed"), receipt.get("error"), [receipt]


@dataclass(frozen=True)
class HttpJudgeConfig:
    endpoint: str
    model: str
    temperature: float = 0
    seed: int = 2026112004
    reasoning_effort: str = "medium"
    max_tokens: int = 16384
    timeout_seconds: float = 1800
    api_key: str | None = None
    enabled: bool = False

    def wire(self):
        return {key: getattr(self, key) for key in
                ("model", "temperature", "seed", "reasoning_effort", "max_tokens", "timeout_seconds")}


class HttpJudgeClient:
    """Direct HTTP only. The caller must explicitly enable actual requests."""
    def __init__(self, config):
        self.config = config
        self.requests = 0
        self.online_requests = 0

    def complete(self, request):
        if not self.config.enabled:
            raise RuntimeError("HTTP Judge is disabled; enable only after selecting and authorizing a Judge")
        url = urlsplit(self.config.endpoint)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
            raise ValueError("Expected an HTTP(S) endpoint without embedded credentials")
        connection_cls = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
        connection = connection_cls(url.hostname, url.port, timeout=self.config.timeout_seconds)
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = "Bearer " + self.config.api_key
        path = url.path.rstrip("/")
        if not path.endswith("/chat/completions"):
            path += "/chat/completions"
        if url.query:
            path += "?" + url.query
        started = monotonic()
        raw = status = parsed = content = reasoning = finish = output_tokens = error = None
        self.requests += 1
        self.online_requests += 1
        try:
            connection.request("POST", path, body=encode(request).encode("utf-8"), headers=headers)
            response = connection.getresponse()
            status = response.status
            raw = response.read().decode("utf-8", errors="replace")
            if status != 200:
                error = f"http_{status}"
            else:
                envelope = json.loads(raw)
                output_tokens = (envelope.get("usage") or {}).get("completion_tokens")
                choice = envelope["choices"][0]
                finish = choice.get("finish_reason")
                message = choice["message"]
                content = message.get("content")
                reasoning = message.get("reasoning", message.get("reasoning_content"))
                parsed = json.loads(content)
        except (OSError, http.client.HTTPException) as exc:
            error = f"transport:{type(exc).__name__}"
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            error = "json_parse_failed"
        finally:
            connection.close()
        return {"attempt": 1, "elapsed_seconds": round(monotonic() - started, 6),
                "http_status": status, "output_tokens": output_tokens, "finish_reason": finish,
                "error": error, "request": deepcopy(request), "raw_response": raw,
                "reasoning_full": reasoning, "assistant_content": content, "parsed": parsed}

    def __call__(self, folder, key, prompt, payload, cfg=None, max_retries=0):
        if max_retries != 0:
            raise ValueError("The frozen checked pipeline owns retries")
        wire = {**self.config.wire(), **(cfg or {})}
        receipt = self.complete(request_body(prompt, payload, wire))
        return receipt["parsed"], receipt["error"], [receipt]
