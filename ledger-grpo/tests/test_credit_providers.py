"""Synthetic provider and exact-request tests; no dataset or live Judge."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from ledger_grpo.credit.judge import (ReplayJudgeClient, ReplayMissError, HttpJudgeClient,
    HttpJudgeConfig, request_body, q2_cache_key)
from ledger_grpo.credit.pipeline import WIRE, execute
from ledger_grpo.credit.config import CreditConfig
from ledger_grpo.credit.group import credit_for_group
from ledger_grpo.credit.providers import (RecordedLedgerProvider, NullLedgerProvider,
    MockLedgerProvider, LiveJudgeLedgerProvider, blank_skippable_q5, q5_skip_candidates)


def fixture():
    conditions = [{"id": "A", "text": "Find the item"}]
    case = {"query_id": "synthetic", "trajectory_id": "synthetic__rep1", "group": "C", "conditions": conditions,
        "steps": [{"step": 1, "before": [{"id": "b1", "text": "Candidate Alpha might fit."}],
            "queries": ["synthetic lookup"], "after": [{"id": "a1", "text": "Candidate Alpha fits."}],
            "after_marker": "", "final_sentences": [{"id": "f1", "text": "Candidate Alpha"}],
            "new_docs": 1, "old_docs": 0, "strict": [],
            "returns": [{"fed_to_model": True, "returned": [{"docid": "d1", "title": "Synthetic document", "sentences": [{"id": "d1s1", "text": "Candidate Alpha fits."}]}]}]}]}
    metadata = {"question": "Find a synthetic item", "answer_type": "item", "gold": "Candidate Alpha", "t_belief": None}
    return case, metadata, {"Q" + str(i): "synthetic Q" + str(i) for i in range(1, 6)}


class SyntheticJudge:
    def __init__(self, votes=(True, True, False)):
        self.votes, self.receipts = votes, []

    def __call__(self, folder, key, prompt, payload, cfg, max_retries=0):
        phase = key.split(".")[0]
        if phase.startswith("Q1"):
            number = 1 if phase == "Q1" else int(phase[-1])
            parsed = {"targets": [{"object": "Candidate Alpha", "conditions": ["A"]}], "restrictions": [{"question_phrase": "synthetic", "words": "blue"}] if self.votes[number - 1] else []}
        elif phase.startswith("Q2"):
            parsed = {"facts": [{"about": "Candidate Alpha", "fact": "fits", "ids": ["d1s1"], "condition": "A", "effect": "满足", "explicit": "是", "broad": "否"}]}
        elif phase == "Q3":
            parsed = {"verdicts": {"E1@1": "用了"}, "claims": []}
        elif phase == "Q4":
            parsed = {"answer": "Candidate Alpha", "linked": [], "dropped": [{"object": "Ghost Entity", "reason": "not suitable"}]}
        else:
            parsed = {"basis": "题外", "basis_conditions": [], "valid": "不成立"}
        receipt = {"request": request_body(prompt, payload, cfg), "parsed": parsed, "error": None, "finish_reason": "stop"}
        self.receipts.append(deepcopy(receipt))
        return parsed, None, [receipt]


class ProviderTests(unittest.TestCase):
    def test_exact_replay_and_missing_request(self):
        case, metadata, prompts = fixture()
        fake = SyntheticJudge()
        expected = execute(case, metadata, prompts, fake)
        replay = ReplayJudgeClient(fake.receipts)
        actual = execute(case, metadata, prompts, replay)
        self.assertEqual(expected, actual)
        self.assertEqual(replay.online_requests, 0)
        request = deepcopy(fake.receipts[0]["request"])
        request["messages"][1]["content"] += " "
        with self.assertRaises(ReplayMissError):
            replay.complete(request)
        self.assertEqual(len(replay.missing_requests), 1)

    def test_repeated_request_receipts_keep_order(self):
        request = request_body("x", {}, WIRE)
        replay = ReplayJudgeClient([{"request": request, "parsed": 1}, {"request": request, "parsed": 2}])
        self.assertEqual(replay.complete(request)["parsed"], 1)
        self.assertEqual(replay.complete(request)["parsed"], 2)
        with self.assertRaises(ReplayMissError):
            replay.complete(request)

    def test_q1_two_agree_stop_and_disagreement_needs_third(self):
        for votes, expected_count in [((True, True, False), 2), ((False, False, True), 2), ((True, False, False), 3)]:
            case, metadata, prompts = fixture()
            full = execute(case, metadata, prompts, SyntheticJudge(votes))
            early = execute(case, metadata, prompts, SyntheticJudge(votes), q1_early_stop=True)
            self.assertEqual(len(early[0]["q1_votes"]["ballots"]), expected_count)
            self.assertEqual(full[0]["record"], early[0]["record"])
            self.assertEqual(full[0]["derived"], early[0]["derived"])

    def test_cache_all_inputs_affect_key(self):
        body = {"题目原文": "synthetic", "条件清单": [{"id": "A"}], "返回句子": [{"text": "example"}], "本步目标": ["X"], "已提到的候选": ["Y"]}
        original = q2_cache_key("prompt", body, WIRE, "version")
        self.assertEqual(original, q2_cache_key("prompt", deepcopy(body), dict(WIRE), "version"))
        for key in ("model", "temperature", "seed", "reasoning_effort", "max_tokens"):
            changed = dict(WIRE)
            changed[key] = str(changed[key]) + "changed"
            self.assertNotEqual(original, q2_cache_key("prompt", body, changed, "version"))
        for key in body:
            changed = deepcopy(body)
            changed[key] = "changed"
            self.assertNotEqual(original, q2_cache_key("prompt", changed, WIRE, "version"))
        self.assertNotEqual(original, q2_cache_key("changed", body, WIRE, "version"))
        self.assertNotEqual(original, q2_cache_key("prompt", body, WIRE, "changed"))

    def test_shared_group_cache_and_conditions(self):
        case, metadata, prompts = fixture()
        group = [{"metadata": {"case": case, "ledger_metadata": metadata}} for _ in range(8)]
        fake = SyntheticJudge()
        provider = LiveJudgeLedgerProvider(fake, prompts, q1_early_stop=True, q3_audit_rate=0)
        results = provider.build(group)
        self.assertEqual(len(results), 8)
        self.assertTrue(all(result.conds is results[0].conds for result in results))
        self.assertEqual(provider.stats["q2_cache_hits"], 14)
        self.assertEqual(provider.stats["q2_cache_misses"], 2)
        self.assertTrue(all(result.records == results[0].records for result in results))
        self.assertTrue(all("gold" not in json.loads(row["request"]["messages"][1]["content"]) for row in fake.receipts))
        self.assertTrue(all(result.records_b and result.derived_b for result in results))
        self.assertFalse(any(row["request"]["messages"][0]["content"] == prompts["Q3"] for row in fake.receipts))

    def test_q3_audit_cannot_change_live_credit_inputs(self):
        case, metadata, prompts = fixture()
        group = [{"metadata": {"case": case, "ledger_metadata": metadata}}]
        audited = LiveJudgeLedgerProvider(SyntheticJudge(), prompts, q3_audit_rate=1).build(group)[0]
        plain = LiveJudgeLedgerProvider(SyntheticJudge(), prompts, q3_audit_rate=0).build(group)[0]
        self.assertTrue(audited.rows[0]["q3_audit"])
        self.assertEqual(audited.derived, plain.derived)
        self.assertEqual(audited.derived_b, plain.derived_b)
        self.assertEqual(audited.records[0]["verdicts"], plain.records[0]["verdicts"])
        self.assertNotIn("Q3", audited.rows[0]["calls"])

    def test_q0_once_per_group_without_gold(self):
        case, metadata, prompts = fixture()
        case.pop("conditions")
        prompts["Q0"] = "synthetic Q0"
        fake = SyntheticJudge()
        seen = []
        def client(folder, key, prompt, payload, cfg, max_retries=0):
            if key.startswith("Q0"):
                seen.append(deepcopy(payload))
                parsed = {"conditions": [{"id": "c1", "text": "first"}, {"id": "c2", "text": "second"}, {"id": "A", "text": "Asked: item"}], "answer_type": "item"}
                return parsed, None, [{"request": request_body(prompt, payload, cfg), "parsed": parsed, "error": None, "finish_reason": "stop"}]
            return fake(folder, key, prompt, payload, cfg, max_retries=max_retries)
        provider = LiveJudgeLedgerProvider(client, prompts)
        results = provider.build([{"metadata": {"case": case, "ledger_metadata": metadata}} for _ in range(8)])
        self.assertEqual(len(seen), 1)
        self.assertEqual(set(seen[0]), {"题目原文"})
        self.assertTrue(all(result.conds is results[0].conds for result in results))
        self.assertEqual(results[0].conds, ["c1", "c2", "A"])

    def test_q5_audit_is_copy_only(self):
        case, metadata, prompts = fixture()
        rows = execute(case, metadata, prompts, SyntheticJudge())
        records = [row["record"] for row in rows]
        self.assertEqual(q5_skip_candidates(records), [(1, 0)])
        copied = blank_skippable_q5(records)
        self.assertEqual(records[0]["excluded"][0]["basis"], "题外")
        self.assertIsNone(copied[0]["excluded"][0]["basis"])
        self.assertIsNone(copied[0]["excluded"][0]["valid"])

    def test_recorded_null_and_mock(self):
        case, metadata, prompts = fixture()
        rows = execute(case, metadata, prompts, SyntheticJudge())
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic__rep1"
            path.mkdir()
            (path / "a.jsonl").write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            (path / "b.jsonl").write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            provider = RecordedLedgerProvider(temporary)
            group = [{"qid": "synthetic", "rollout": 0, "gold": metadata["gold"]}]
            result = provider.build(group, config=CreditConfig.from_preset("C_W_v211"))[0]
            self.assertEqual(result.records, [row["record"] for row in rows])
            self.assertEqual(result.conds, ["A"])
            self.assertGreater(result.tokens["F"], 0)
            current = provider.build(group)[0]
            self.assertIn("q3_audit", current.records[0])
            self.assertIn("程序", current.records[0]["verdicts"]["E1@1"]["reason"])
            self.assertEqual(current.records_b, current.records)
            self.assertEqual(current.derived_b, current.derived)
        self.assertEqual(NullLedgerProvider().build([{}])[0].records, [])
        mocked = MockLedgerProvider().build([{"units": [{"unit_id": 1}, {"unit_id": "F"}]}])[0]
        self.assertEqual(len(mocked.records), 1)
        self.assertEqual(mocked.derived[0]["view"]["A"][0], "✔")

    def test_http_default_does_not_connect(self):
        client = HttpJudgeClient(HttpJudgeConfig("http://unused.invalid/v1", "synthetic"))
        with self.assertRaises(RuntimeError):
            client.complete(request_body("x", {}, WIRE))
        self.assertEqual(client.online_requests, 0)
        provider = LiveJudgeLedgerProvider(client, {})
        self.assertEqual(provider.cfg["model"], "synthetic")

    def test_incomplete_recorded_pass_causes_whole_group_fallback(self):
        case, metadata, prompts = fixture()
        rows = execute(case, metadata, prompts, SyntheticJudge())
        frozen = "\n".join(json.dumps(row) for row in rows)
        for empty_pass in ("a", "b"):
            with self.subTest(empty_pass=empty_pass), TemporaryDirectory() as temporary:
                for i in (1, 2):
                    target = Path(temporary) / f"synthetic__rep{i}"
                    target.mkdir()
                    for variant in ("a", "b"):
                        (target / f"{variant}.jsonl").write_text(
                            "" if i == 2 and variant == empty_pass else frozen, encoding="utf-8"
                        )
                provider = RecordedLedgerProvider(temporary)
                trajectories = [{"qid": "synthetic", "rollout": i, "gold": metadata["gold"]} for i in (0, 1)]
                results = [
                    dict(records=result.records, derived=result.derived, conds=result.conds,
                         records_b=result.records_b, derived_b=result.derived_b, tokens={1: 4, "F": 2},
                         outcome={"Y": i == 0, "submitted": True})
                    for i, result in enumerate(provider.build(trajectories))
                ]
                credits = credit_for_group(results)
                self.assertTrue(all(credit["log"].get("ledger_fallback") for credit in credits))

    def test_replay_uses_secondary_q2_even_when_primary_receipts_repeat(self):
        case, metadata, prompts = fixture()
        with TemporaryDirectory() as temporary:
            paths, group = [], []
            for i in (1, 2):
                entry = deepcopy(case)
                entry["trajectory_id"] = f"synthetic__rep{i}"
                group.append({"metadata": {"case": entry, "ledger_metadata": metadata}})
                (Path(temporary) / entry["trajectory_id"]).mkdir()
            for variant, fact in (("a", "primary observation"), ("b", "secondary observation")):
                for item in group:
                    entry = item["metadata"]["case"]
                    source = SyntheticJudge()

                    def send(*args, **kwargs):
                        _, key, _, _, _ = args
                        parsed, error, receipts = source(*args, **kwargs)
                        if key.startswith("Q2"):
                            parsed["facts"][0]["fact"] = fact
                        return parsed, error, receipts

                    rows = execute(entry, metadata, prompts, send)
                    path = Path(temporary) / entry["trajectory_id"] / f"{variant}.jsonl"
                    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
                    paths.append(path)
            replay = ReplayJudgeClient.from_state_files(paths)
            results = LiveJudgeLedgerProvider(replay, prompts, q3_audit_rate=0).build(group)
            for item in results:
                self.assertEqual(item.records[0]["evidence"][0]["fact"], "primary observation")
                self.assertEqual(item.records_b[0]["evidence"][0]["fact"], "secondary observation")
            self.assertEqual(replay.online_requests, 0)

    def test_recorded_behavioural_rows_honor_new_route_threshold(self):
        case, metadata, prompts = fixture()
        case["steps"] = [dict(deepcopy(case["steps"][0]), step=i, returns=[], new_docs=0)
                         for i in range(1, 5)]
        rows = execute(case, metadata, prompts, SyntheticJudge(), use_q3=False, k_hold=3)
        holds = [row["step"] for row in rows if "坚持无据候选" in row["derived"]["route"]]
        self.assertTrue(holds)
        with TemporaryDirectory() as temporary:
            target = Path(temporary) / case["trajectory_id"]
            target.mkdir()
            (target / "a.jsonl").write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            result = RecordedLedgerProvider(temporary).load(case["trajectory_id"], config=CreditConfig(k_hold=9))
        self.assertFalse(any("坚持无据候选" in row["route"] for row in result.derived))


if __name__ == "__main__":
    unittest.main()
