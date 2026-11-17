"""Instrument the unchanged FSDP pilot within a private coexistence update."""
import os
from pathlib import Path
import sys

import torch

from hf_pilot_train import file_sha256, load_step_inputs, main, run_update, write_once
import hf_pilot_train
from ledger_grpo import coexist_test_grade


def validated_test_inputs(native, score):
    grade = Path(os.environ["COEXIST_TEST_OUTCOME_RECEIPT"]).resolve()
    scores = torch.load(score, map_location="cpu", weights_only=True)
    if (Path(score).resolve().parent != grade.parent or scores.get("test_only") is not True
            or scores.get("result_source") != coexist_test_grade.RESULT_SOURCE
            or scores.get("strict_rule_sha256") != file_sha256(Path(coexist_test_grade.__file__))
            or scores.get("input_binding", {}).get("test_outcomes_sha256") != file_sha256(grade)):
        raise ValueError("isolated optimizer requires the authorized snapshot-bound test grade")
    prepared, manifest = load_step_inputs(native, score)
    manifest.update(test_only=True, result_source=coexist_test_grade.RESULT_SOURCE,
                    strict_rule_sha256=scores["strict_rule_sha256"], test_outcomes_sha256=file_sha256(grade))
    return prepared, manifest


def measured_update(*args, **kwargs):
    result = run_update(*args, **kwargs)
    rank = int(os.environ["LOCAL_RANK"])
    output = Path(sys.argv[sys.argv.index("--output-root") + 1])
    torch.cuda.synchronize()
    write_once(output / f"MEMORY-rank{rank}.json", {
        "rank": rank, "checkpoint_started": False,
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(rank),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(rank),
    })
    return result


if __name__ == "__main__":
    hf_pilot_train.load_step_inputs = validated_test_inputs
    hf_pilot_train.run_update = measured_update
    raise SystemExit(main())
