from concurrent.futures import Future
import json
import threading
from types import SimpleNamespace

import pytest

import coexist_controller
from ledger_grpo import browsecomp_adapter, hf_native


def test_unreadable_docid_result_is_an_explicit_bound_exclusion(tmp_path, monkeypatch):
    def invalid_docid(*args, **kwargs):
        raise json.JSONDecodeError("invalid document JSON", "", 0)

    monkeypatch.setattr(coexist_controller, "label_trajectory", invalid_docid)
    monkeypatch.setattr(browsecomp_adapter, "native_trajectory", lambda raw, reward: {"id": "t", "query_id": "q"})
    monkeypatch.setattr(hf_native, "native_turn_layout", lambda native: {"response_mask": [0, 1]})
    root = tmp_path / "diagnostics"
    root.mkdir()
    source = tmp_path / "original.json"
    source.write_text("{}", encoding="utf-8")
    original_bytes = source.read_bytes()
    batch = SimpleNamespace(path=tmp_path, snapshot="snapshot", questions={"q": "synthetic"},
                            common=dict(evidence=None, tokenizer=None, environment={}, labeler_versions={"code_commit": "rev"}),
                            core_path=tmp_path / "handoff.jsonl", diagnostic_path=root / "r1-sidecar.jsonl",
                            lock=threading.Lock())
    grade = Future()
    grade.set_result({"correct": None})
    timing = {"traj_id": "t", "task_id": "q"}
    core = Future()
    core.set_result(coexist_controller.Batch.label_core(batch, source, timing, grade))
    coexist_controller.Batch.label_m3(batch, core)
    score = json.loads(batch.core_path.read_text(encoding="utf-8"))
    diagnostic = json.loads(batch.diagnostic_path.read_text(encoding="utf-8"))
    assert score["policy_snapshot_id"] == diagnostic["policy_snapshot_id"] == "snapshot"
    assert score["grounding"] is None
    assert score["recording_complete"] is False
    assert score["outcome"] is None
    assert score["events"] == []
    assert score["response_mask"] == [0, 1]
    assert score["exclusion_reason"].endswith("JSONDecodeError")
    assert diagnostic["status"] == "excluded"
    assert source.read_bytes() == original_bytes


def test_archive_requires_the_original_snapshot_and_an_ungraded_roster(tmp_path):
    original = tmp_path / "previous" / "batch-1"
    rollout = original / "rollout"
    rollout.mkdir(parents=True)
    result = original.parent / "result.json"
    result.write_text('{"layout":"A","policy_snapshot_id":"original"}', encoding="utf-8")
    batch = SimpleNamespace(path=tmp_path / "batch-1", layout="A", snapshot="wrong", tracks=[("q", "t")])
    with pytest.raises(ValueError, match="different policy"):
        coexist_controller.Batch.ingest_archive(batch, original)
    batch.snapshot = "original"
    (rollout / "TRAIN_BATCH.json").write_text(
        '{"trajectories":[{"query_id":"q","id":"t","terminal":"MODEL_FINAL_STOP","reward":0}]}', encoding="utf-8")
    with pytest.raises(ValueError, match="ungraded batch"):
        coexist_controller.Batch.ingest_archive(batch, original)
