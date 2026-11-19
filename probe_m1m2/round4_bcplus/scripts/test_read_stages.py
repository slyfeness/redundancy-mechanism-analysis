import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from native_stages import stage_costs
from read_stages import outcome_record, parse_hits


MARKERS = {"<tool_call>": 10, "</tool_call>": 11, "<tool_response>": 20, "</tool_response>": 21}


class StageExtractionTests(unittest.TestCase):
    def test_executed_trailing_call_counts_only_observed_suffix(self):
        trace = {"rounds": [{"round_id": 1, "response_received": True, "tool_calls": [{"id": "a"}, {"id": "b"}],
                             "token_accounting": {"completion_token_ids": [2, 10, 7, 11, 10, 8, 9]}}],
                 "tool_events": [{"round_id": 1}, {"round_id": 1}]}
        cost = stage_costs(trace, MARKERS)
        self.assertEqual(cost["trailing_open_rounds"], [1])
        self.assertEqual(cost["stages"]["R1:T2"]["generated_tokens"], 3)
        self.assertEqual(cost["total_generated_tokens"], 7)
        self.assertEqual(cost["shared_tokens"], 1)

    def test_mcp_text_block_conversion(self):
        wrapped = [{"type": "text", "text": '[{"docid":"125"}]'}]
        self.assertEqual(parse_hits(wrapped), ["125"])
        with self.assertRaises(ValueError):
            parse_hits([{"docid": "malformed"}])

    def test_strict_repeat_needs_exact_content_and_query(self):
        task = {"run_id": "1__rep1", "query_id": "1", "seed": 10, "repetition_id": 1}
        a = '[{"docid":"1","snippet":"alpha"}]'
        b = '[{"docid":"1","snippet":"beta"}]'
        events = []
        rounds = []
        for rid, (query, result) in enumerate((("Find X", a), ("  find x!  ", a), ("find X", b)), 1):
            prompt = [1, 2] if rid == 1 else [1, 20, 7, 21]
            messages = [] if rid == 1 else [{"role": "tool", "tool_call_id": str(rid-1),
                                             "content": events[-1]["exact_result"]}]
            rounds.append({"round_id": rid, "response_received": True, "tool_calls": [{"id": str(rid)}],
                           "token_accounting": {"completion_token_ids": [2, 10, 3, 11], "prompt_token_ids": prompt},
                           "actor_visible_messages": messages})
            events.append({"round_id": rid, "tool_call_id": str(rid), "dispatch_utc": str(rid), "dispatch_order": 1,
                           "event_id": rid, "tool_name": "search-server-search", "tool_ordinal": 1,
                           "exact_arguments": json.dumps({"query": query}), "exact_result": result})
        trace = {"metadata": {"task": task}, "rounds": rounds, "tool_events": events}
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            data = json.dumps(trace).encode()
            (folder / "trajectory.json").write_bytes(data)
            (folder / "TERMINAL.json").write_text(json.dumps({
                "status": "SAFETY_CEILING_STOP", "actor_calls": 3, "search_calls": 3,
                "trajectory": {"sha256": hashlib.sha256(data).hexdigest()},
            }))
            row, stages = outcome_record(task, folder, folder / "none", MARKERS, {"1"}, set())
        self.assertEqual([s["strict_repeat"] for s in stages], [False, True, False])
        self.assertEqual([s["repeat_union"] for s in stages], [False, True, True])
        self.assertEqual([s["c_new_any"] for s in stages], [1, 0, 0])
        self.assertEqual(row["return_tokens"], 6)


if __name__ == "__main__":
    unittest.main()
