import json
import unittest

from ledger_grpo.native_tool_coordinates import recorded_tool_coordinates
from ledger_grpo.sampler_tool_adapter import measure_sampler_batch


class ByteTokenizer:
    def decode(self, tokens, *, skip_special_tokens):
        return bytes(tokens).decode("ascii")

    def __call__(self, text, **kwargs):
        return {"input_ids": list(text.encode("ascii")), "offset_mapping": [(i, i+1) for i in range(len(text))]}


def response(prompt, completion, calls=()):
    prompt_ids, completion_ids = list(prompt.encode("ascii")), list(completion.encode("ascii"))
    return {"prompt_token_ids": prompt_ids,
            "usage": {"prompt_tokens": len(prompt_ids), "completion_tokens": len(completion_ids)},
            "choices": [{"token_ids": completion_ids, "message": {"tool_calls": list(calls)},
                         "logprobs": {"content": [{"bytes": [i], "logprob": -.01} for i in completion_ids]}}]}


class NativeToolCoordinatesTests(unittest.TestCase):
    def setUp(self):
        self.tokenizer = ByteTokenizer()
        self.calls = [
            {"id": "first", "function": {"name": "search", "arguments": '{"query":"answer"}'}},
            {"id": "second", "function": {"name": "open", "arguments": '{"doc_id":"d"}'}},
        ]
        self.results = ['{"results":["d"]}', '{"text":"evidence"}']
        self.events = [{"event_id": str(i), "tool_call_id": c["id"], "tool_name": c["function"]["name"],
                        "exact_arguments": c["function"]["arguments"], "exact_result": result}
                       for i, (c, result) in enumerate(zip(self.calls, self.results), 1)]
        self.envelopes = [f'<tool_call><function={e["tool_name"]}>{e["exact_arguments"]}</function></tool_call>'
                          for e in self.events]
        self.current = response("before", "reason"+self.envelopes[0]+"\n"+self.envelopes[1], self.calls)
        self.request = {"messages": [dict(role="tool", tool_call_id=call["id"], content=result)
                                     for call, result in zip(self.calls, self.results)]}
        self.rendered = "before\n" + "\n".join(f"<tool_response>\n{result}\n</tool_response>" for result in self.results)
        self.next = response(self.rendered, "answer")

    def test_parallel_calls_have_disjoint_policy_intervals_and_bound_return_counts(self):
        got = recorded_tool_coordinates(self.current, self.events, next_request=self.request,
                                        next_response=self.next, tokenizer=self.tokenizer, offset=10)
        expected_starts = [16, 17+len(self.envelopes[0])]
        self.assertEqual([row["event_tokens"] for row in got],
                         [[start, start+len(call)] for start, call in zip(expected_starts, self.envelopes)])
        self.assertEqual([row["event_cost"]["returned_tokens"] for row in got], list(map(len, self.results)))

    def test_response_coverage_and_exact_message_binding_are_required(self):
        for request, received in ((None, self.next), (self.request, None),
                                  ({"messages": list(reversed(self.request["messages"]))}, self.next),
                                  (self.request, response(self.rendered.replace("evidence", "wrong"), "answer"))):
            with self.assertRaises(ValueError):
                recorded_tool_coordinates(self.current, self.events, next_request=request, next_response=received,
                                          tokenizer=self.tokenizer)

    def test_non_roundtripping_prompt_cannot_produce_a_return_cost(self):
        class AlteredTokenizer(ByteTokenizer):
            def __call__(self, text, **kwargs):
                return {"input_ids": [], "offset_mapping": []}
        with self.assertRaises(ValueError):
            recorded_tool_coordinates(self.current, self.events, next_request=self.request,
                                      next_response=self.next, tokenizer=AlteredTokenizer())

    def test_sampler_adapters_bind_to_recorded_json_serialization(self):
        for dataset, id_key, return_key in (("sage", "tool_call_id", "observation"),
                                            ("scicode", "call_id", "model_visible_return")):
            with self.subTest(dataset=dataset):
                name = "open" if dataset == "sage" else "read_code"
                arguments = {"doc_id": "d"} if dataset == "sage" else {}
                observed = ('{"text":"evidence","id":"d"}' if dataset == "sage"
                            else '{"status":"OK","current_code":"evidence"}')
                parsed = dict(sorted(json.loads(observed).items()))
                event = {"event_id": "a", id_key: "second", "name": name,
                         "arguments": arguments, return_key: parsed}
                request = {"messages": [{"role": "tool", "tool_call_id": "second", "content": observed}]}
                call = {"id": "second", "function": {"name": name, "arguments": json.dumps(arguments)}}
                envelope = f"<tool_call><function={name}>{json.dumps(arguments)}</function></tool_call>"
                current = response("before", envelope, [call])
                next_response = response(f"<tool_response>\n{observed}\n</tool_response>", "answer")
                measured = measure_sampler_batch(dataset, current, [event], next_request=request,
                                                 next_response=next_response, tokenizer=self.tokenizer)
                self.assertEqual(measured[0]["event_cost"]["returned_tokens"], len(observed))
                event[return_key]["tampered"] = True
                with self.assertRaises(ValueError):
                    measure_sampler_batch(dataset, current, [event], next_request=request,
                                          next_response=next_response, tokenizer=self.tokenizer)
