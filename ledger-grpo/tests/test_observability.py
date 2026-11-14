"""Real file/event tests; no model, network, credentials, or trainer required."""

import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ObservabilityTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module("ledger_grpo.observability")
        except ImportError as exc:
            self.fail(f"observability contract is missing: {exc}")

    def writer(self, path, **kwargs):
        return self.api().EventWriter(path, run_id="run-a", training_seed=17,
                                      config_hash="cfg-a", **kwargs)

    def rollout(self, **updates):
        row = dict(traj_id="traj-a", task_id="task-a", sample_id="sample-a", split="train",
                   outcome=1, complete=True, cost=10.0, cost_unit="policy_tokens",
                   gen_tokens=10, grounding_score=1.0, process_valid=True,
                   redundant_token_fraction=.2)
        row.update(updates)
        return row

    def test_rank_nonzero_never_creates_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "absent" / "events.jsonl"
            writer = self.writer(path, rank=1)
            self.assertFalse(writer.emit("run.started", {}, event_id="start"))
            self.assertFalse(path.parent.exists())

    def test_idempotence_survives_reopen_and_conflict_does_not_append(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            writer = self.writer(path)
            self.assertTrue(writer.emit("rollout.scored", self.rollout(), event_id="r1", batch_id="b1"))
            original = path.read_bytes()
            reopened = self.writer(path)
            self.assertFalse(reopened.emit("rollout.scored", self.rollout(), event_id="r1", batch_id="b1"))
            with self.assertRaises(api.EventConflictError):
                reopened.emit("rollout.scored", self.rollout(outcome=0), event_id="r1", batch_id="b1")
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(len(api.read_events(path)), 1)

    def test_schema_strips_nested_private_text_and_nonfinite_metrics_become_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            self.writer(path).emit("optimizer.result", {
                "update_id": "u1", "status": "committed", "source": "optimizer_callback",
                "steps_before": 0, "steps_after": 1, "api_key": "SECRET_SENTINEL",
                "metrics": {"entropy": float("nan"), "lr": .0001,
                            "grad_norm": float("inf"), "prompt": "SECRET_SENTINEL"},
                "error_message": "SECRET_SENTINEL",
            }, event_id="u1")
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("SECRET_SENTINEL", content)
            self.assertNotIn("NaN", content)
            self.assertNotIn("Infinity", content)
            metrics = json.loads(content)["payload"]["metrics"]
            self.assertIsNone(metrics["entropy"])
            self.assertIsNone(metrics["grad_norm"])
            self.assertEqual(metrics["lr"], .0001)

    def test_wrong_types_and_bad_outcomes_are_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            writer = self.writer(path)
            for update in ({"outcome": 2}, {"gen_tokens": True}, {"grounding_score": 1.1},
                           {"complete": "true"}, {"cost": -1}):
                with self.subTest(update=update), self.assertRaises(ValueError):
                    writer.emit("rollout.scored", self.rollout(**update), event_id="bad")
            self.assertFalse(path.exists())

    def test_computed_batch_never_counts_as_committed_optimizer_update(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            writer = self.writer(path)
            writer.emit("advantage.computed", {"valid_row_count": 2}, event_id="c1", batch_id="b1",
                        trainer_iteration=1, optimizer_steps_committed=99)
            summary = api.summarize_events(api.read_events(path))["runs"]["run-a"]
            self.assertEqual(summary["computed_batch_count"], 1)
            self.assertEqual(summary["optimizer_committed_count"], 0)
            self.assertIsNone(summary["last_committed_step"])
            writer.emit("optimizer.result", {
                "update_id": "u1", "status": "skipped", "source": "optimizer_callback",
                "reason": "amp_overflow", "steps_before": 0, "steps_after": 0,
            }, event_id="o1")
            summary = api.summarize_events(api.read_events(path))["runs"]["run-a"]
            self.assertEqual(summary["optimizer_skipped_count"], 1)
            self.assertEqual(summary["optimizer_committed_count"], 0)

    def test_false_commit_and_discontinuous_optimizer_history_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            writer = self.writer(path)
            base = dict(update_id="u1", status="committed", source="optimizer_callback", steps_before=0)
            with self.assertRaises(ValueError):
                writer.emit("optimizer.result", dict(base, steps_after=0), event_id="bad")
            writer.emit("optimizer.result", dict(base, steps_after=1), event_id="o1")
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                writer.emit("optimizer.result", dict(base, update_id="u2", steps_before=4, steps_after=5), event_id="o2")
            self.assertEqual(path.read_bytes(), original)

    def test_duplicate_logical_samples_do_not_inflate_summary(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            writer = self.writer(path)
            writer.emit("rollout.scored", self.rollout(), event_id="r1", batch_id="b1")
            self.assertFalse(writer.emit("rollout.scored", self.rollout(), event_id="r1-retry", batch_id="b1"))
            with self.assertRaises(api.EventConflictError):
                writer.emit("rollout.scored", self.rollout(traj_id="different", outcome=0), event_id="r2", batch_id="b1")
            self.assertEqual(api.summarize_events(api.read_events(path))["runs"]["run-a"]["train"]["sample_count"], 1)

    def test_missing_grounding_has_coverage_and_failures_still_cost_money(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            writer = self.writer(path)
            writer.emit("rollout.scored", self.rollout(), event_id="r1", batch_id="b1")
            writer.emit("rollout.scored", self.rollout(traj_id="t2", sample_id="s2", outcome=0,
                        cost=30, grounding_score=0, process_valid=False), event_id="r2", batch_id="b1")
            row = api.summarize_events(api.read_events(path))["runs"]["run-a"]["train"]
            self.assertEqual(row["accuracy"], .5)
            self.assertEqual(row["cost_per_success"], 40)
            self.assertEqual(row["grounding_score"]["mean"], 1)
            self.assertEqual(row["grounding_score"]["coverage"], .5)
            self.assertEqual(row["process_valid_rate"], .5)

    def test_abstention_uses_observed_judge_calls_not_candidate_span_count(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            writer = self.writer(path)
            writer.emit("rollout.scored", self.rollout(judge_counts={"yes": 2, "no": 1, "uncertain": 1, "error": 1},
                        abstain_span_counts={"R1": 9}), event_id="r1", batch_id="b1")
            writer.emit("rollout.scored", self.rollout(traj_id="t2", sample_id="s2", judge_counts=None),
                        event_id="r2", batch_id="b1")
            row = api.summarize_events(api.read_events(path))["runs"]["run-a"]["train"]
            self.assertEqual(row["judge_counts"]["coverage"], .5)
            self.assertEqual(row["judge_abstention_rate"], .25)
            self.assertEqual(row["judge_error_rate"], .2)
            self.assertEqual(row["abstain_span_counts"]["totals"]["R1"], 9)
            self.assertIsNone(row["api_usage"]["totals"]["prompt_tokens"])

    def test_training_seeds_and_evaluation_manifests_are_never_pooled(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a.jsonl", Path(tmp) / "b.jsonl"
            self.writer(a).emit("rollout.scored", self.rollout(split="eval", evaluation_id="eval-1"), event_id="r1")
            api.EventWriter(b, run_id="run-b", training_seed=29, config_hash="cfg-a").emit(
                "rollout.scored", self.rollout(outcome=0, split="eval", evaluation_id="eval-1"), event_id="r1")
            runs = api.summarize_events(api.read_events(a) + api.read_events(b))["runs"]
            self.assertEqual(runs["run-a"]["training_seed"], 17)
            self.assertEqual(runs["run-b"]["training_seed"], 29)
            self.assertEqual(runs["run-a"]["evaluations"]["eval-1"]["accuracy"], 1)
            self.assertEqual(runs["run-b"]["evaluations"]["eval-1"]["accuracy"], 0)
            self.assertEqual(runs["run-a"]["train"]["sample_count"], 0)

    def test_reader_tolerates_only_unfinished_tail_for_live_rendering(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            self.writer(path).emit("run.started", {}, event_id="start")
            with path.open("ab") as output:
                output.write(b'{"event_id":')
            self.assertEqual(len(api.read_events(path, allow_incomplete_tail=True)), 1)
            with self.assertRaises(ValueError):
                api.read_events(path)
            with self.assertRaises(ValueError):
                self.writer(path)

    def test_writer_refuses_unterminated_line_instead_of_corrupting_next_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            self.writer(path).emit("run.started", {}, event_id="start")
            path.write_bytes(path.read_bytes().rstrip(b"\n"))
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                self.writer(path)
            self.assertEqual(path.read_bytes(), original)

    def test_collector_reads_only_complete_metric_prefix_and_never_claims_training(self):
        self.api()
        script = Path(__file__).resolve().parents[1] / "scripts" / "collect_pilot_monitor.py"
        self.assertTrue(script.exists(), "local pilot collector is missing")
        spec = importlib.util.spec_from_file_location("pilot_collector", script)
        collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(collector)
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / "preflight", Path(tmp) / "monitor"
            source.mkdir()
            collector.collect(preflight_dir=source, output_dir=output, run_id="pilot", training_seed=None)
            self.assertTrue((output / "monitor.html").exists())
            collector.collect(preflight_dir=source, output_dir=output, run_id="pilot", training_seed=None, state="running")
            collector.collect(preflight_dir=source, output_dir=output, run_id="pilot", training_seed=None, state="pending")
            collector.collect(preflight_dir=source, output_dir=output, run_id="pilot", training_seed=None, state="running")
            running = self.api().summarize_events(self.api().read_events(output / "metrics.jsonl"))["runs"]["pilot"]
            self.assertEqual(running["latest_status"]["status"], "running")
            collector.collect(preflight_dir=source, output_dir=output, run_id="pilot", training_seed=None, state="pending")
            current = self.api().summarize_events(self.api().read_events(output / "metrics.jsonl"))["runs"]["pilot"]
            self.assertEqual(current["latest_status"]["status"], "pending")
            (source / "MANIFEST.json").write_text(json.dumps({"groups_selected": ["q1"]}), encoding="utf-8")
            folder = source / "t1"
            folder.mkdir()
            (folder / "metrics.json").write_text('{"trajectory_id":', encoding="utf-8")
            collector.collect(preflight_dir=source, output_dir=output, run_id="pilot", training_seed=None,
                              state="running")
            (folder / "metrics.json").write_text(json.dumps({"trajectory_id": "t1", "error_count": "bad"}), encoding="utf-8")
            malformed = collector.collect(preflight_dir=source, output_dir=output, run_id="pilot", training_seed=None,
                                          state="running")
            self.assertEqual(malformed["input_issue_count"], 1)
            metric = {"trajectory_id": "t1", "query_id": "q1", "outcome": 1,
                      "turns": 2, "policy_tokens": 40, "qa_ok": True, "error_count": 0,
                      "grounding": 1., "span_count": 0, "judge_calls": 3, "judge_attempts": 4,
                      "judge_usage": {"prompt_tokens": 80, "completion_tokens": 9, "api_key": "SECRET_SENTINEL"},
                      "judge_seconds": 2., "prompt": "SECRET_SENTINEL"}
            (folder / "metrics.json").write_text(json.dumps(metric), encoding="utf-8")
            collector.collect(preflight_dir=source, output_dir=output, run_id="pilot", training_seed=None,
                              state="running")
            (source / "RESULT.json").write_text(json.dumps({"state": "completed", "optimizer_steps_committed": 0,
                "trajectories": 1, "groups": 1, "valid_rows": 1, "effective_policy_tokens": 40,
                "changed_advantage_tokens": 4, "max_absolute_advantage_delta": .2,
                "judge_requests": 4, "judge_prompt_tokens": 90, "judge_completion_tokens": 12,
                "method_metrics": {"valid_row_count": 1, "process_row_count": 1, "all_wrong_groups": [],
                                   "invalid_training_groups": [], "qa_disabled_groups": []}}), encoding="utf-8")
            collector.collect(preflight_dir=source, output_dir=output, run_id="pilot", training_seed=None)
            before = (output / "metrics.jsonl").read_bytes()
            collector.collect(preflight_dir=source, output_dir=output, run_id="pilot", training_seed=None)
            self.assertEqual((output / "metrics.jsonl").read_bytes(), before)
            self.assertNotIn(b"SECRET_SENTINEL", before)
            events = self.api().read_events(output / "metrics.jsonl")
            summary = self.api().summarize_events(events)["runs"]["pilot"]
            self.assertEqual(summary["optimizer_committed_count"], 0)
            self.assertEqual(summary["train"]["sample_count"], 0)
            self.assertEqual(summary["audits"]["preflight"]["sample_count"], 1)
            self.assertEqual(summary["latest_status"]["status"], "completed")
            self.assertEqual(summary["latest_status"]["artifact_state"], "partial")
            self.assertEqual(summary["latest_status"]["api_usage"]["prompt_tokens"], 90)
            self.assertEqual(summary["computed_batch_count"], 1)

    def test_rollout_helper_uses_real_pipeline_and_does_not_copy_private_text(self):
        api = self.api()
        from ledger_grpo.examples import synthetic_examples
        from ledger_grpo.pipeline import analyze_trajectory
        traces, deltas = synthetic_examples()
        trace = traces[0]
        report = analyze_trajectory(trace, deltas=deltas[trace["traj_id"]])
        report["private"] = "SECRET_SENTINEL"
        payload = api.rollout_payload(trace, report)
        self.assertEqual(payload["outcome"], 1)
        self.assertEqual(payload["gen_tokens"], sum(trace["response_mask"]))
        self.assertGreater(payload["redundant_token_fraction"], 0)
        self.assertNotIn("SECRET_SENTINEL", json.dumps(payload))
        self.assertNotIn("ledger", payload)
        self.assertIsNone(payload["judge_counts"])

    def test_advantage_helper_excludes_masked_tokens_and_does_not_invent_r_d_attribution(self):
        api = self.api()
        import torch
        result = {
            "metrics": {"valid_row_count": 1, "process_row_count": 1, "all_wrong_groups": ["bad"],
                        "invalid_training_groups": [], "qa_disabled_groups": []},
            "valid_rows": torch.tensor([True, False]),
            "effective_response_mask": torch.tensor([[1, 1, 0], [0, 0, 0]]),
            "advantages": torch.tensor([[1., .5, 999.], [999., 999., 999.]]),
            "trajectory_advantage": torch.tensor([1., 999.]),
            "accuracy_advantage": torch.tensor([1., 999.]),
            "efficiency_advantage": torch.tensor([0., 999.]),
            "grounding_advantage": torch.tensor([0., 999.]),
        }
        payload = api.advantage_payload(result, task_ids=["good", "bad"])
        self.assertEqual(payload["effective_policy_tokens"], 2)
        self.assertEqual(payload["final_advantage"]["mean"], .75)
        self.assertEqual(payload["actual_changed_tokens"], 1)
        self.assertEqual(payload["local_downshift"]["mean"], .25)
        self.assertEqual(payload["valid_group_count"], 1)
        self.assertIsNone(payload["r_changed_tokens"])
        self.assertIsNone(payload["d_changed_tokens"])

    def test_evaluation_summary_does_not_expose_raw_text_or_claim_paired_ci(self):
        api = self.api()
        rows = [dict(task_id="a", sample_id="s1", outcome=1, complete=True, cost=10, prompt="SECRET_SENTINEL"),
                dict(task_id="b", sample_id="s1", outcome=0, complete=True, cost=30)]
        payload = api.evaluation_payload(rows, evaluation_id="e1", checkpoint_id="c1", eval_manifest_id="m1")
        self.assertEqual(payload["accuracy"], .5)
        self.assertEqual(payload["cost_per_success"], 40)
        self.assertNotIn("SECRET_SENTINEL", json.dumps(payload))
        self.assertNotIn("paired_accuracy_ci", payload)
        with self.assertRaises(ValueError):
            api.evaluation_payload(rows + [rows[0]], evaluation_id="e1", checkpoint_id="c1", eval_manifest_id="m1")

    def test_evaluation_helper_drops_grounding_placeholder_and_rejects_mixed_runs(self):
        api = self.api()
        rows = [dict(task_id="a", sample_id="s1", outcome=1, complete=True, cost=10, grounding_score=1, process_valid=True, run_id="r1"),
                dict(task_id="b", sample_id="s1", outcome=0, complete=True, cost=20, grounding_score=0, process_valid=False, run_id="r1")]
        payload = api.evaluation_payload(rows, evaluation_id="e1", checkpoint_id="c1", eval_manifest_id="m1")
        self.assertEqual(payload["mean_grounding"], 1.)
        self.assertEqual(payload["grounding_coverage"], .5)
        rows[1]["run_id"] = "r2"
        with self.assertRaises(ValueError):
            api.evaluation_payload(rows, evaluation_id="e1", checkpoint_id="c1", eval_manifest_id="m1")

    def test_static_html_is_escaped_and_cli_updates_existing_page(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            path, html = Path(tmp) / "events.jsonl", Path(tmp) / "monitor.html"
            writer = api.EventWriter(path, run_id="<script>alert(1)</script>", training_seed=17, config_hash="cfg")
            writer.emit("rollout.scored", self.rollout(), event_id="r1", trainer_iteration=1, batch_id="b1")
            api.render_monitor(path, html, refresh_seconds=3)
            content = html.read_text(encoding="utf-8")
            self.assertNotIn("<script>alert(1)</script>", content)
            self.assertIn("&lt;script&gt;", content)
            self.assertIn("http-equiv=\"refresh\"", content)
            writer.emit("rollout.scored", self.rollout(traj_id="t2", sample_id="s2", outcome=0),
                        event_id="r2", trainer_iteration=2, batch_id="b2")
            result = subprocess.run([sys.executable, "-m", "ledger_grpo.observability", str(path),
                                     "--output", str(html), "--refresh-seconds", "3"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotEqual(content, html.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
