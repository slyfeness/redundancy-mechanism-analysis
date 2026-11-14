"""Exercise both candidate collection loops using saved and mocked responses."""

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from ledger_grpo.native_capture import capture_status, native_chat_request, native_chat_segment


def read(path):
    return json.loads(path.read_bytes())


def verify_candidates(folder, served_response):
    results = {}
    for dataset in ("sage", "scicode"):
        path = folder / f"run_{dataset}_native.py"
        namespace = {"__name__": f"test_{dataset}_sampler"}
        # The SciCode runtime's POSIX resource controls are only used when
        # executing generated tests. No test program is run in this replay.
        stubs = {"resource": SimpleNamespace()} if os.name == "nt" else {}
        with patch.dict("sys.modules", stubs), patch.dict(os.environ, {"SAGE_BATCH_OUT": str(folder)}):
            exec(compile(path.read_bytes(), str(path), "exec"), namespace)
        namespace["Index"] = lambda: SimpleNamespace(close=lambda: None)
        server = namespace["Server"].__new__(namespace["Server"])
        server.url = "http://127.0.0.1:1"
        payload = deepcopy(served_response)
        choice = payload["choices"][0]
        tool = "submit_answer" if dataset == "sage" else "submit_code"
        arguments = {"answer": "fixture"} if dataset == "sage" else {"code": "def identity(value):\n    return value\n"}
        choice["message"] = {"role": "assistant", "content": "", "tool_calls": [
            {"type": "function", "id": "fixture-call", "function": {"name": tool, "arguments": json.dumps(arguments)}},
        ]}
        choice["finish_reason"] = "tool_calls"

        def collect(root):
            if dataset == "sage":
                return namespace["execute"]({"pilot_id": "fixture_1", "dataset": "fixture", "corpus_id": "fixture",
                                             "question": "Fixture task"}, server, root), root / "fixture_1"
            task = {"problem_description_main": "Fixture task", "sub_steps": [{"step_number": 1}]}
            return namespace["run_step"](task, 0, [], server, root, 1, 42), root / "step_01"

        capture_results = {}
        for valid in (True, False):
            response = deepcopy(payload)
            if not valid:
                response["choices"][0]["token_ids"] = None
            body = json.dumps(response).encode()
            with TemporaryDirectory() as directory, patch.object(namespace["requests"], "post", return_value=SimpleNamespace(
                    status_code=200, content=body)) as post:
                outcome, artifact = collect(Path(directory))
                post.assert_called_once()
                actual = post.call_args.kwargs["data"]
                request = json.loads(actual)
                assert request == native_chat_request(request)
                assert read(artifact / "round_01_request.json") == request
                assert (artifact / "round_01_request.body").read_bytes() == actual
                assert (artifact / "round_01_response.body").read_bytes() == body
                assert read(artifact / "round_01_response.json") == response
                assert outcome["rounds"][0]["native_capture"] == capture_status(response)
                assert outcome["rounds"][0]["native_capture"]["valid"] is valid
                assert len(outcome["tool_events"]) == int(valid)
                expected = "MODEL_FINAL_STOP" if dataset == "sage" else "MODEL_SUBMIT_STOP"
                assert outcome["stop_reason"] == (expected if valid else "NATIVE_CAPTURE_INVALID")
                capture_results["valid" if valid else "missing_ids"] = outcome["stop_reason"]
        results[dataset] = {"candidate_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), **capture_results}
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--first-request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    trajectory = read(args.trajectory)
    rounds = [row for row in trajectory["rounds"] if row.get("response_received") is True]
    request = read(args.first_request)
    assert request["messages"] == rounds[0]["actor_visible_messages"]
    assert request == native_chat_request(request)
    completion_tokens = 0
    for row in rounds:
        segment = native_chat_segment(row["raw_response"])
        assert segment["prompt_ids"] == row["token_accounting"]["prompt_token_ids"]
        assert segment["completion_ids"] == row["token_accounting"]["completion_token_ids"]
        completion_tokens += len(segment["completion_ids"])
    report = {"scope": "Saved BrowseComp native replay and mocked candidate transports. No model generation.",
              "recorded_first_request_sha256": hashlib.sha256(args.first_request.read_bytes()).hexdigest(),
              "recorded_trajectory_sha256": hashlib.sha256(args.trajectory.read_bytes()).hexdigest(),
              "verified_recorded_rounds": len(rounds), "recorded_completion_tokens": completion_tokens,
              "candidate_paths": verify_candidates(args.candidates, rounds[0]["raw_response"])}
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(report, out, indent=2)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
