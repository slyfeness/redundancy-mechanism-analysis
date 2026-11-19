"""Retry an unresolved outcome once, with the exact original grader request."""
import hashlib
import json
import sys
from pathlib import Path

from score import LocalJudge, PROMPT


def load(path):
    return json.loads(path.read_bytes())


def retry_client(url, model, timeout):
    if timeout not in {60, 240}:
        raise ValueError("Unsupported isolated retry timeout")
    judge = LocalJudge(url, model, timeout=60, max_tokens=4096, cache_size=0)
    if timeout > 60:
        # The shared constructor deliberately caps its normal timeout at 60 s.
        # Preserve the exact request/parser and no-redirect loopback transport.
        open_request = judge.opener.open

        def open_with_retry_deadline(request, *, timeout):
            return open_request(request, timeout=240)

        judge.opener.open = open_with_retry_deadline
    return judge


def main(run, selection, out, url, model, timeout="60", attempt="1"):
    questions = {row["id"]: row for row in load(selection / "evaluation_private.json")}
    tasks = load(selection / "task_manifest.json")["tasks"]
    assert url.startswith("http://127.0.0.1:") and model == "gpt-oss-120b"
    for task in tasks:
        tid = task["run_id"]
        original = run / "verdicts" / f"{tid}.json"
        if not original.is_file():
            continue
        prior = load(original)
        if prior["correct"] is not None:
            continue
        assert prior["status"] == "MODEL_FINAL_STOP" and prior["judge"] == model
        assert prior["run_id"] == tid and prior["seed"] == task["seed"]
        folder = run / "trajectories" / tid
        trace_bytes = (folder / "trajectory.json").read_bytes()
        assert hashlib.sha256(trace_bytes).hexdigest() == load(folder / "TERMINAL.json")["trajectory"]["sha256"]
        trace = json.loads(trace_bytes)
        assert trace["metadata"]["task"] == task
        question = questions[task["query_id"]]
        assert hashlib.sha256(question["question"].encode()).hexdigest() == task["question_sha256"]
        judge = retry_client(url, model, int(timeout))
        retry = dict(prior, judge_retry=int(attempt), judge_transport_timeout=int(timeout),
                     prior_receipt_sha256=hashlib.sha256(original.read_bytes()).hexdigest())
        try:
            verdict = judge._request(PROMPT, {"question": question["question"], "references": question["answers"],
                                            "submission": trace["rounds"][-1]["content"]}, system_prefix="")
            assert set(verdict) == {"correct"} and type(verdict["correct"]) is bool
            retry.update(correct=verdict["correct"], judge_usage=judge.usage, judge_error=None)
        except Exception as error:
            retry["judge_error"] = type(error).__name__
            retry["judge_error_cause"] = type(error.__cause__).__name__ if error.__cause__ is not None else None
        with (out / f"{tid}.json").open("x", encoding="utf-8") as handle:
            json.dump(retry, handle)
        print("retry", tid, retry["correct"], retry["judge_error"], flush=True)


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:4]), *sys.argv[4:])
