from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest

from redundancy_judge.common import JudgeFailure, exact_quote
from redundancy_judge.init_task_ledger import init_task_ledger
from redundancy_judge.update_evidence_ledger import update_evidence_ledger


spec = spec_from_file_location("ledger_diagnosis", Path(__file__).resolve().parents[2] /
                               "scripts/diagnose_phase1_ledger.py")
diagnosis = module_from_spec(spec)
spec.loader.exec_module(diagnosis)


@pytest.mark.parametrize(("source", "quote", "kind", "flag"), [
    ("aaaa", "aa", "multiple", None),
    ("one town", "one town", "one_other_validation", None),
    ("one town", None, "unlinked", None),
    ("one\ntown", "one town", "zero", "whitespace"),
    ("one—town", "one town", "zero", "punctuation_character_or_escaping"),
    ("the blue sky is open; far away the pale moon", "the blue sky ... the pale moon", "zero",
     "noncontiguous_segments"),
])
def test_quote_diagnostics_do_not_authorize_evidence(source, quote, kind, flag):
    hits, result, flags = diagnosis.quote_analysis(source, quote)
    assert result == kind
    if flag:
        assert hits == 0 and flag in flags
        with pytest.raises(JudgeFailure):
            exact_quote(source, {"quote": quote})


def test_quote_hook_preserves_original_failure():
    context = {"trajectory_id": "fixture-1", "event_id": "fixture-1:1"}
    judge = SimpleNamespace(calls=[{"component": "evidence_update", "cache_key": "cached",
                                   "coordinates": context}])
    captures = []
    wrapped = diagnosis.observe_quote(captures, judge, exact_quote)
    with pytest.raises(JudgeFailure, match="absent or ambiguous"):
        wrapped("same same", {"quote": "same", "candidate": "entity"})
    assert captures[0]["source_text"] == "same same"
    assert captures[0]["cache_key"] == "cached"
    assert captures[0]["event_id"] == "fixture-1:1"


def test_batch_hook_identifies_already_validated_row_lost_to_later_validation():
    class Judge:
        context = {"trajectory_id": "fixture-1", "event_id": "fixture-1:1"}

        def ask(self, kind, payload):
            if kind == "task_constraints":
                return {"constraints": [{"quote": "target"}], "uncertain": False}
            return {"uncertain": False, "updates": [
                {"candidate": "Ada", "constraint_id": "C1", "state": "supported", "quote": "Ada qualifies"},
                {"candidate": "Other", "constraint_id": "missing", "state": "supported", "quote": "Ada"},
            ]}

    judge = Judge()
    task, initial = init_task_ledger("Find the target.", judge)
    stage = {"parse_status": "ok", "stage_id": "fixture-1:S001"}
    event = {"event_id": "1", "return_text": "Ada qualifies.", "visible_next": True}
    impacts = []
    reference = update_evidence_ledger(task, initial, stage, event, judge)
    wrapped = diagnosis.inspect_update(update_evidence_ledger, impacts)
    assert wrapped(task, initial, stage, event, judge) == reference
    assert reference[0]["support"] == {}
    assert impacts[0]["buffered_valid_updates"][0]["quote"] == "Ada qualifies"


def test_cache_miss_remains_offline(tmp_path):
    (tmp_path / "task_constraints.md").write_text("fixture", encoding="utf8")
    judge = diagnosis.OfflineJudge({"url": "http://127.0.0.1:9/v1", "model": "fixture"},
                                   tmp_path, tmp_path / "cache", {})
    with pytest.raises(JudgeFailure, match="cache entry is missing"):
        judge.ask("task_constraints", {"question": "fixture"})
    assert judge.calls[-1]["cache_hit"] is False
    assert not (tmp_path / "cache").exists()
