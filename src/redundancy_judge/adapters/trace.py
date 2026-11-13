"""Read a native recorder trajectory and its independent result."""

import hashlib
import json
from pathlib import Path


def sha256(payload):
    return hashlib.sha256(payload).hexdigest()


def load_trajectory(path, *, result=None, question=None, environment=None, synthetic=False):
    """Do not infer the result from the recorded assistant's answer."""
    path = Path(path)
    payload = path.read_bytes()
    raw = json.loads(payload)
    metadata = raw["metadata"]
    task = metadata["task"]
    question_id, trajectory_id = str(task["query_id"]), str(task["run_id"])
    rounds, events = raw["rounds"], raw["tool_events"]
    if not isinstance(rounds, list) or not isinstance(events, list):
        raise ValueError("rounds and tool_events must be lists")
    recorded_question = next((
        msg["content"] for row in rounds
        for msg in row.get("actor_visible_messages", [])
        if msg.get("role") == "user" and isinstance(msg.get("content"), str)
    ), None)
    if question is None:
        question = recorded_question
    if not isinstance(question, str) or not question.strip():
        raise ValueError("No recorded question")
    if recorded_question is not None and question != recorded_question:
        raise ValueError("Provided question differs from recorded question")
    question_hash = sha256(question.encode("utf-8"))
    if task.get("question_sha256") not in (None, question_hash):
        raise ValueError("Question hash differs from the task manifest")
    if result is not None:
        if (result.get("label") not in {"C", "W", "N"} or not result.get("source")
                or result.get("trajectory_id", trajectory_id) != trajectory_id):
            raise ValueError("Invalid independent result")
    return {
        "schema_version": "phase1.v1",
        "question_id": question_id,
        "trajectory_id": trajectory_id,
        "question": question,
        "question_sha256": question_hash,
        "result": result,
        "termination_reason": metadata.get("terminal_status", "UNKNOWN"),
        "input_sha256": sha256(payload),
        "source_path": str(path),
        "model": metadata.get("model"),
        "model_revision": metadata.get("model_revision"),
        "tokenizer_revision": metadata.get("tokenizer_revision"),
        "seed": task.get("seed"),
        "environment": environment or {},
        "rounds": rounds,
        "tool_events": events,
        "guard_attempts": raw.get("unsent_guard_attempts") or [],
        "synthetic": synthetic,
    }


class NativeByteTokenizer:
    """Read byte-level BPE ID byte pieces for an authoritative tokenizer revision.

    This reads native IDs and cannot tokenize or produce new IDs. Special/added
    vocabulary entries use their literal UTF-8 bytes, as in Qwen's native map.
    """

    def __init__(self, path, revision):
        payload = Path(path).read_bytes()
        tokenizer = json.loads(payload)
        if (tokenizer.get("decoder", {}).get("type") != "ByteLevel"
                or tokenizer.get("model", {}).get("type") != "BPE"):
            raise ValueError("NativeByteTokenizer requires a ByteLevel BPE tokenizer")
        if not isinstance(revision, str) or not revision:
            raise ValueError("Tokenizer revision is required")
        self.revision = revision
        self.sha256 = sha256(payload)
        alphabet = list(range(33, 127)) + list(range(161, 173)) + list(range(174, 256))
        escaped = [byte for byte in range(256) if byte not in alphabet]
        mapping = dict(zip(map(chr, alphabet + list(range(256, 256 + len(escaped)))), alphabet + escaped))
        self.pieces = {
            token_id: bytes(mapping[char] for char in word)
            for word, token_id in tokenizer["model"]["vocab"].items()
        }
        self.pieces.update({item["id"]: item["content"].encode("utf-8") for item in tokenizer["added_tokens"]})

    def native_bytes(self, ids):
        """Return a byte sequence and its exact original token boundaries."""
        parts = [self.pieces[token_id] for token_id in ids]
        return bytes_and_boundaries(parts)


def bytes_and_boundaries(parts):
    offset = 0
    bounds = {0: 0}
    for index, part in enumerate(parts, start=1):
        if not part:
            raise ValueError("Empty native token piece has an ambiguous boundary")
        offset += len(part)
        bounds[offset] = index
    return b"".join(parts), bounds
