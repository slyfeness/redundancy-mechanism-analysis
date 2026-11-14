"""Canonical identities and validated evidence coordinates."""

from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4


class JudgeFailure(ValueError):
    """A model or protocol failure that must remain visible to the caller."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identity(value):
    return sha256(canonical(value).encode()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(canonical(value) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def require(condition, message):
    if not condition:
        raise JudgeFailure(message)


def exact_quote(source, item):
    quote = item.get("quote")
    require(isinstance(quote, str) and bool(quote.strip()), "empty evidence quote")
    start = item.get("start")
    end = item.get("end")
    if start is None and end is None:
        start = source.find(quote)
        require(start >= 0 and source.find(quote, start + 1) < 0, "evidence quote absent or ambiguous")
        end = start + len(quote)
    require(type(start) is int and type(end) is int and 0 <= start < end <= len(source)
            and source[start:end] == quote, "evidence quote does not match its character span")
    return {"start": start, "end": end, "quote": quote, "coordinate": "source_char"}


def candidate_name(value):
    import unicodedata
    if not isinstance(value, str) or not value.strip():
        return None
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())
