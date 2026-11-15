from hashlib import sha256
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from redundancy_judge import cli
from redundancy_judge.adapters.trace import load_trajectory
from redundancy_judge.init_task_ledger import init_task_ledger, init_task_ledger_frozen
from scripts.freeze_constraints_v4 import freeze_rows


QUESTION = "Whether the editor of a journal works in Chile? Give the full title in English."
DIGEST = sha256(QUESTION.encode()).hexdigest()


def source_row():
    row = lambda text, keywords, origin: {
        "text": text, "keywords": keywords, "source": origin, "certain": True,
    }
    return {"question_id": "q", "question": QUESTION, "question_sha256": DIGEST,
            "error": None, "audit_error": None, "extraction": {"answer_type": "title",
                "answer_format": "Give the full title in English", "global_notes": []},
            "not_constraints": [{"id": "C1", "reason": "fixture objection"}],
            "constraints": [
                row("source without keywords", ["absent"], "extract"),
                row("spurious substring", ["her"], "audit"),
                row("no keywords", [], "audit"),
                row("write the full title in English", ["full title"], "audit"),
                row("editor works in Chile", ["ＣＨＩＬＥ"], "audit"),
            ]}


def fixture_frozen():
    return next(iter(freeze_rows([source_row()], [{"question_id": "q", "question": QUESTION}],
                                 expected_questions=1)))


def test_filter_audit_only_and_renumber_without_deleting_extract_objections():
    result = fixture_frozen()
    assert [row["constraint_id"] for row in result["constraints"]] == ["C1", "C2"]
    assert [row["origin"] for row in result["constraints"]] == ["extract", "audit"]
    assert result["constraints"][0]["keywords"] == ["absent"]
    assert result["constraints"][1]["keywords"] == ["ＣＨＩＬＥ"]
    assert result["provenance"]["objections"] == source_row()["not_constraints"]
    assert [row["reason"] for row in result["dropped"]] == [
        "audit_keyword_not_in_question", "audit_keyword_not_in_question", "audit_duplicates_answer_format",
    ]


@pytest.mark.parametrize("damage", ["hash", "coverage", "duplicate"])
def test_freezer_rejects_identity_or_coverage_errors(damage):
    rows = [source_row()]
    if damage == "hash":
        rows[0]["question_sha256"] = "0" * 64
    if damage == "coverage":
        rows.clear()
    if damage == "duplicate":
        rows.append(rows[0])
    with pytest.raises(ValueError):
        freeze_rows(rows, [{"question_id": "q", "question": QUESTION}], expected_questions=1)


def test_frozen_and_legacy_specs_validate():
    row = fixture_frozen()
    task, ledger = init_task_ledger_frozen(QUESTION, row)
    assert task["constraint_source"] == "frozen_v4" and task["uncertain"] is False
    assert task["question_sha256"] == DIGEST
    assert task["constraints"] == row["constraints"] and ledger["open_gaps"] == ["C1", "C2"]
    assert all("source" not in item for item in task["constraints"])
    schema_path = Path(cli.__file__).with_name("schemas") / "phase1.schema.json"
    schema = json.loads(schema_path.read_bytes())
    validator = Draft202012Validator({**schema, "$ref": "#/$defs/TaskSpec"})
    validator.validate(task)
    legacy, _ = init_task_ledger(QUESTION, cli.SyntheticJudge())
    validator.validate(legacy)


@pytest.mark.parametrize("row", [None, {"question_sha256": "0" * 64}])
def test_frozen_initializer_rejects_missing_or_mismatched_questions(row):
    task, ledger = init_task_ledger_frozen(QUESTION, row)
    assert task["status"] == "annotation_error" and task["error"]
    assert task["uncertain"] and not task["constraints"] and not ledger["open_gaps"]


@pytest.mark.parametrize("mode", ["match", "missing", "mismatch"])
def test_frozen_cli_never_asks_model_for_question_constraints(tmp_path, monkeypatch, mode):
    fixture = Path(__file__).parents[1] / "fixtures/final_only.json"
    trace = load_trajectory(fixture)
    question = trace["question"]
    digest = sha256(question.encode()).hexdigest()
    row = {"question_id": trace["question_id"], "trajectory_id": trace["trajectory_id"], "question": question,
           "sha256": trace["input_sha256"], "termination_reason": trace["termination_reason"], "split": "dev",
           "result": "C", "result_source": "fixture", "path": str(fixture), "environment": "fixture",
           "deterministic_tools": []}
    index, frozen_path, config_path = (tmp_path / name for name in ("index.jsonl", "frozen.jsonl", "config.json"))
    cli.write_jsonl(index, [row])
    fixed = {**fixture_frozen(), "question_sha256": digest if mode == "match" else DIGEST,
             "question_id": trace["question_id"]}
    cli.write_jsonl(frozen_path, [fixed] if mode != "missing" else [])
    out = tmp_path / "out"
    config_path.write_text(json.dumps({"mode": "synthetic", "input_index": str(index), "output_dir": str(out),
        "frozen_constraints": str(frozen_path), "judge": {"version": "fixture"}, "code_commit": "fixture"}),
        encoding="utf-8")
    original = cli.SyntheticJudge.ask
    calls = []

    def judge(self, kind, payload):
        calls.append(kind)
        if kind == "task_constraints":
            raise AssertionError("unexpected model fallback")
        return original(self, kind, payload)

    monkeypatch.setattr(cli.SyntheticJudge, "ask", judge)
    assert cli.main(["annotate", "--config", str(config_path)]) == 0
    assert calls == ["final_candidate"]
    output = out / "synthetic"
    task = cli.jsonl(output / "task_specs.jsonl")[0]
    assert task["status"] == ("ok" if mode == "match" else "annotation_error")
    if mode != "match":
        assert ("SHA-256 mismatch" if mode == "mismatch" else "missing frozen v4 constraints") in task["error"]
    manifest = cli.read_json(output / "run_manifest.json")
    digest = sha256(frozen_path.read_bytes()).hexdigest()
    assert manifest["freeze"]["frozen_constraints_sha256"] == digest
    bundle = cli.read_json(next((output / "bundles").glob("*.json")))
    assert bundle["provenance"]["frozen_constraints_sha256"] == digest
