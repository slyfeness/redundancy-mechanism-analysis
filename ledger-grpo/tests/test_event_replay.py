import json
import unittest

from ledger_grpo.event_replay import delivered_repeat_witnesses


class EventReplayTests(unittest.TestCase):
    def test_structured_result_binds_despite_json_serialization_order(self):
        events = {
            1: [{"event_id": "a", "tool_call_id": "one", "exact_result": '{"x": 1, "y": 2}'}],
            2: [{"event_id": "b", "tool_call_id": "two", "exact_result": '{"x": 1, "y": 2}'}],
        }
        rounds = [
            {"round_id": 1, "request_sent": True, "response_received": True},
            {"round_id": 2, "request_sent": True, "response_received": True, "actor_visible_messages": [
                {"role": "tool", "tool_call_id": "one", "content": '{"y":2,"x":1}'},
            ]},
        ]
        def canonical(text):
            return json.dumps(json.loads(text), sort_keys=True)
        witnesses = delivered_repeat_witnesses(rounds, events, event_key=lambda event: ("read", event["exact_result"]),
                                               normalize_return=canonical)
        self.assertEqual(witnesses, {"b": "a"})

    def test_unobserved_return_and_sibling_call_cannot_witness_repeat(self):
        events = {
            1: [{"event_id": "a", "tool_call_id": "one", "exact_result": "r"},
                {"event_id": "b", "tool_call_id": "two", "exact_result": "r"}],
            2: [{"event_id": "c", "tool_call_id": "three", "exact_result": "r"}],
        }
        rounds = [
            {"round_id": 1, "request_sent": True, "response_received": True},
            {"round_id": 2, "request_sent": True, "response_received": False, "actor_visible_messages": [
                {"role": "tool", "tool_call_id": "one", "content": "r"},
            ]},
        ]
        self.assertEqual(delivered_repeat_witnesses(rounds, events, event_key=lambda event: event["exact_result"]), {})
