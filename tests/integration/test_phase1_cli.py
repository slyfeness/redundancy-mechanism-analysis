import json
from pathlib import Path
from threading import Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from redundancy_judge.adapters.model import ModelJudge, RESPONSE_SCHEMAS
from redundancy_judge.cli import jsonl, main, write_jsonl
from redundancy_judge.common import JudgeFailure, read_json
import pytest


def test_freeze_and_replay_only_run_with_no_training(tmp_path):
    fixture = Path(__file__).resolve().parents[1] / "fixtures/final_only.json"
    from redundancy_judge.adapters.trace import load_trajectory
    rows = []
    for split in ("dev", "calibration", "audit"):
        raw = json.loads(fixture.read_bytes())
        raw["metadata"]["task"].update(query_id=split, run_id=split)
        path = tmp_path / (split + ".json")
        path.write_text(json.dumps(raw), encoding="utf-8")
        trace = load_trajectory(path)
        rows.append({"path": str(path), "question": trace["question"], "question_id": split,
                     "trajectory_id": split, "result": "C", "result_source": "fixture",
                     "Y": 1, "termination_reason": trace["termination_reason"], "sha256": trace["input_sha256"],
                     "environment": "fixed", "deterministic_tools": [], "split": split})
    index = tmp_path / "index.jsonl"
    write_jsonl(index, rows)
    config = {"mode": "synthetic", "input_index": str(index), "output_dir": str(tmp_path / "run"),
              "run_dir": str(tmp_path / "run/synthetic"), "code_commit": "fixture",
              "judge": {"version": "synthetic"}, "reward": {"w_g": 0}, "workers": 2}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    args = ["--config", str(config_path)]
    assert main(["inspect", *args]) == 0
    assert main(["annotate", *args, "--split", "dev", "--limit-questions", "5"]) == 0
    assert main(["annotate", *args, "--split", "all", "--resume", "--replay-only"]) == 0
    folder = Path(config["run_dir"])
    assert len(jsonl(folder / "trajectory_summaries.jsonl")) == 3
    assert read_json(folder / "run_manifest.json")["synthetic"] is True
    assert main(["export-review", *args]) == 2
    assert main(["reward-preview", *args]) == 0
    assert read_json(folder / "reward_preview_summary.json")["optimizer_steps"] == 0
    config_path.write_text(json.dumps({**config, "code_commit": "different"}), encoding="utf-8")
    assert main(["annotate", *args, "--resume", "--replay-only"]) == 2


def test_structured_local_judge_matches_cache_identity_and_rejects_missing_cache(tmp_path):
    received = []

    class Server(BaseHTTPRequestHandler):
        def respond(self, payload):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            assert self.path == "/v1/models"
            self.respond({"data": [{"id": "fixture-model"}]})

        def do_POST(self):
            assert self.path == "/v1/chat/completions"
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            content = json.dumps({"constraints": [{"quote": "city"}], "uncertain": False})
            self.respond({"model": "fixture-model", "choices": [
                {"finish_reason": "stop", "message": {"content": content}}]})

    prompts = Path(__file__).resolve().parents[2] / "prompts"
    with ThreadingHTTPServer(("127.0.0.1", 0), Server) as service:
        thread = Thread(target=service.serve_forever, daemon=True)
        thread.start()
        config = {"url": f"http://127.0.0.1:{service.server_port}/v1", "model": "fixture-model"}
        try:
            judge = ModelJudge(config, prompts, tmp_path, {"code_commit": "fixture"})
            judge.check_service()
            actual = judge.ask("task_constraints", {"question": "Which city?"})
        finally:
            service.shutdown()
            thread.join()
    assert received[0]["response_format"]["json_schema"]["schema"] == RESPONSE_SCHEMAS["task_constraints"]
    replay = ModelJudge(config, prompts, tmp_path, {"code_commit": "fixture"}, replay_only=True)
    assert replay.ask("task_constraints", {"question": "Which city?"}) == actual
    with pytest.raises(JudgeFailure, match="missing"):
        replay.ask("task_constraints", {"question": "different input"})
