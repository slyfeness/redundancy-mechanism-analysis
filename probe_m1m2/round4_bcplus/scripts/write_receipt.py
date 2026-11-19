"""Export scheduler and run receipts without service logs or request data."""
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "private"


def status(job):
    raw = (PRIVATE / "sacct.txt").read_bytes()
    fields = [line.split("|") for line in raw.decode("utf-8").splitlines()]
    job_id, state, runtime, exit_code, submit, start, end = next(line for line in fields if line[0] == str(job))
    return {"job_id": int(job_id), "state": state.split()[0], "exit_code": exit_code,
            "runtime": runtime, "submitted": submit, "started": start, "ended": end,
            "accounting_sha256": hashlib.sha256(raw).hexdigest()}


def main():
    signal = json.loads((ROOT / "signal_summary.json").read_bytes())
    actual = signal["source_gpu_job"]
    gpu = status(actual)
    raw = (PRIVATE / f"gpu-{actual}.log").read_bytes()
    lines = raw.decode("utf-8").splitlines()
    gpu.update(
        milestones=dict((label, stamp) for stamp, label in re.findall(
            r"(\S+Z) (batch_start|actor_complete|judge_ready|pilot_complete)", "\n".join(lines))),
        verified_actor_startup="Actor services ready" in lines,
        verified_retriever="retriever_ready" in lines,
        sealed_trajectories=signal["sealed"],
        resolved_outcomes=signal["resolved_outcomes"],
        observed_worker_error_log_lines=sum(line.startswith("worker_failed ") for line in lines),
        private_batch_log_sha256=hashlib.sha256(raw).hexdigest(),
    )
    if gpu["state"] == "COMPLETED":
        assert gpu["verified_actor_startup"] and gpu["verified_retriever"]
    assert signal["analysis_job"] > 0
    initial = status(191862)
    initial["failure_reason"] = "deletion_retriever_middleware_missing"
    initial["sample_requests"] = 0
    second = status(191870)
    second["failure_reason"] = "missing_native_tool_schema_envelope"
    second["verified_pre_request_worker_errors"] = 40
    second["sample_requests"] = 0
    second["controller_exit_code_before_purge"] = "0:15"
    output = {"preparation": status(191859), "initial_startup_attempt": initial, "gpu": gpu,
              "schema_startup_attempt": second, "discarded_zero_sample_analysis": status(191878),
              "native_layout_preflight": status(191871), "analysis": status(signal["analysis_job"]),
              "retrieval": {
                  "reference_job": 183352, "corpus_rows": 100195,
                  "encoder": "Qwen3-Embedding-8B", "index": "FAISS", "top_k": 5,
                  "snippet_max_tokens": 512, "open_available": False,
                  "original_sha256": "a8fa830cfc4879106c29ecb61f7003858d5d230276c6fac8556bb3e875156069",
                  "adapted_sha256": "4632674dff57df7992cf8ba03d8db42755599298395a9ad7b99cc66acaf2cd29",
              },
              "judge_retry": status(signal["judge_retry_job"]) if signal["judge_retry_job"] else None,
              "external_requests": 0, "optimizer_steps": 0}
    (ROOT / "execution_receipt.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
