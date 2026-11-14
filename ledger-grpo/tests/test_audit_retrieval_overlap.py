import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from audit_retrieval_overlap import audit_searches


def event(index, round_id, query, documents, *, call_id=None):
    return {
        "event_id": index, "round_id": round_id, "tool_ordinal": index,
        "tool_call_id": call_id or str(index), "tool_name": "search-server-search",
        "exact_arguments": json.dumps({"query": query}),
        "exact_result": json.dumps([{"docid": key, "snippet": text} for key, text in documents]),
        "raw_mcp_response": {"isError": False, "content": [{"type": "text", "text": "recorded"}]},
    }


def request(round_id, *delivered, sent=True, received=True):
    return {
        "round_id": round_id, "request_sent": sent, "response_received": received,
        "actor_visible_messages": [{"role": "tool", "tool_call_id": row["tool_call_id"],
                                    "content": row["exact_result"]} for row in delivered],
    }


class RetrievalOverlapAuditTests(unittest.TestCase):
    def test_union_of_delivered_snippets_identifies_changed_query_and_partial_overlap(self):
        a = event(1, 1, "a", [("1", "first")])
        b = event(2, 2, "b", [("2", "second")])
        c = event(3, 3, "c", [("2", "second"), ("1", "first")])
        d = event(4, 4, "d", [("1", "updated text"), ("2", "second")])
        e = event(5, 5, "c", [("2", "second"), ("1", "first")])
        got = audit_searches({"rounds": [request(1), request(2, a), request(3, b), request(4, c),
                                        request(5, d)], "tool_events": [a, b, c, d, e]})
        self.assertEqual(got["covered_search_events"], 5)
        self.assertEqual(got["fully_seen_events"], 2)
        self.assertEqual(got["fully_seen_new_arguments_events"], 1)
        self.assertEqual(got["partial_overlap_events"], 1)
        self.assertEqual(got["unseen_only_events"], 2)
        self.assertEqual(got["exact_repeat_events"], 1)

    def test_siblings_and_unsent_returns_are_not_part_of_the_visible_prefix(self):
        a = event(1, 1, "a", [("1", "first")])
        b = event(2, 1, "b", [("1", "first")])
        c = event(3, 3, "c", [("1", "first")])
        empty = event(4, 3, "d", [])
        got = audit_searches({"rounds": [request(1), request(2, a, b, sent=False), request(3)],
                              "tool_events": [a, b, c, empty]})
        self.assertEqual(got["fully_seen_events"], 0)
        self.assertEqual(got["unseen_only_events"], 3)
        self.assertEqual(got["empty_return_events"], 1)

    def test_reused_call_ids_cannot_establish_a_delayed_witness(self):
        a = event(1, 1, "a", [("1", "first")], call_id="reused")
        b = event(2, 2, "b", [("1", "first")], call_id="reused")
        c = event(3, 3, "c", [("1", "first")])
        got = audit_searches({"rounds": [request(1), request(2), request(3, b)],
                              "tool_events": [a, b, c]})
        self.assertEqual(got["fully_seen_events"], 0)
        self.assertEqual(got["reused_call_id_events"], 1)

    def test_monitor_only_shows_overlap_for_bound_evaluation(self):
        from mirror_pilot_monitor import _evaluation_table

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            latest = root / "latest"
            latest.mkdir()
            source = latest / "EVAL-targeted.json"
            source.write_bytes(b'{"sample_count": 2}')
            audit = {"protocol": "prefix-visible-exact-docid-and-snippet-overlap-v1",
                     "arms": {"targeted": {"summary_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                                          "sample_count": 2,
                                          "totals": {"fully_seen_events": 3, "fully_seen_new_arguments_events": 1,
                                                     "covered_search_events": 8, "recorded_search_events": 9}}}}
            (root / "RETRIEVAL_OVERLAP_AUDIT.json").write_text(json.dumps(audit), encoding="utf-8")
            rendered = _evaluation_table(latest)
            self.assertIn("<td>1.50</td><td>0.50</td><td>8/9</td>", rendered)
            source.write_bytes(b'{"sample_count": 3}')
            self.assertNotIn("<td>1.50</td><td>0.50</td><td>8/9</td>", _evaluation_table(latest))
