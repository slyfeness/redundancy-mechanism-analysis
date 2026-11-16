import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[2] / "scripts/replay_docid_r1_tiers.py"
spec = importlib.util.spec_from_file_location("replay_docid_r1_tiers", SCRIPT)
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


def test_replay_restores_exact_passage_order_from_archived_request():
    before = {"evidence_passages": {"1": "first sorted", "9": "first seen"}}
    target = {"provided_passage_ids": ["P9", "P1"]}
    restored = replay.restore_request_order(before, target)
    assert list(restored["evidence_passages"]) == ["9", "1"]
    assert restored["evidence_passages"] == before["evidence_passages"]
    assert list(before["evidence_passages"]) == ["1", "9"]


def test_replay_refuses_archive_passages_with_different_membership():
    before = {"evidence_passages": {"1": "one", "9": "nine"}}
    target = {"provided_passage_ids": ["P9", "P3"]}
    with pytest.raises(ValueError, match="membership"):
        replay.restore_request_order(before, target)


def test_cached_intent_preserves_wire_order_for_the_second_request(tmp_path, monkeypatch):
    first = {"seeking": "a", "entity": "b", "attribute": "c"}
    sorted_response = dict(sorted(first.items()))
    receipt = {"raw_response": json.dumps({"choices": [{"message": {"content": json.dumps(first)}}]})}
    monkeypatch.setattr(replay.ModelJudge, "ask_m3", lambda *_args: sorted_response)
    monkeypatch.setattr(replay, "read_json", lambda _path: receipt)
    judge = replay.CachedJudge.__new__(replay.CachedJudge)
    judge.cache = tmp_path / "model_cache"
    judge.cache_reads = replay.Counter()
    output = judge.ask_m3("intent", {}, {}, "e1")
    assert list(output) == list(first)
