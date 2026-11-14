import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "index_browsecomp.py"


def module():
    spec = importlib.util.spec_from_file_location("index_browsecomp", SCRIPT)
    index = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(index)
    return index


def test_question_splits_are_stable_and_keep_near_duplicates_together():
    sample = {str(i): f"Identifier {i} a unique case {'z' * (i + 1)}" for i in range(10)}
    sample.update({"0": "Who founded Example Bank in 1818?", "1": "Who founded Example Bank in 1818!"})
    index = module()
    split = index.split_questions(sample, 9)
    assert split == index.split_questions(dict(reversed(list(sample.items()))), 9)
    assert split["0"] == split["1"]
    assert {label: list(split.values()).count(label) for label in ("dev", "calibration", "audit")} == {
        "dev": 6, "calibration": 2, "audit": 2,
    }


def test_missing_correctness_and_unusable_outcomes_are_separate():
    idx = module()
    from pytest import raises

    assert idx.result_of("CORRECT", "MODEL_FINAL_STOP") == ("C", 1)
    assert idx.result_of("INCORRECT", "MODEL_FINAL_STOP") == ("W", 0)
    assert idx.result_of("NO_FINAL", "SAFETY_CEILING_STOP") == ("N", 0)
    assert idx.result_of("UNCERTAIN", "MODEL_FINAL_STOP") == ("UNCERTAIN", None)
    assert idx.result_of("NO_FINAL", "OBSERVABILITY_ERROR") == ("N", None)
    with raises(ValueError):
        idx.result_of("CORRECT", "CONTEXT_LIMIT_STOP")
