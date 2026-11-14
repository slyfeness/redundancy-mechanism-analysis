import unittest

from ledger_grpo.native_capture import NativeCaptureError, native_chat_request, native_chat_segment


def recorded_response():
    return {
        "prompt_token_ids": [7, 8], "usage": {"prompt_tokens": 2, "completion_tokens": 2},
        "choices": [{"index": 0, "token_ids": [11, 12],
                     "logprobs": {"content": [{"logprob": -.1, "bytes": [120]},
                                              {"logprob": -.2, "bytes": None}]}}],
    }


class NativeCaptureTests(unittest.TestCase):
    def test_request_keeps_sampling_and_adds_observation_fields(self):
        source = {"temperature": 1, "top_p": .8, "seed": 40, "max_tokens": 30, "messages": []}
        request = native_chat_request(source)
        self.assertEqual(request, dict(source, stream=False, logprobs=True, return_token_ids=True))
        self.assertNotIn("return_token_ids", source)
        for override in ({"stream": True}, {"n": 2}):
            with self.assertRaises(NativeCaptureError):
                native_chat_request(dict(source, **override))

    def test_actual_prompt_and_completion_identifiers_and_logprobs_are_preserved(self):
        segment = native_chat_segment(recorded_response())
        self.assertEqual(segment["prompt_ids"], [7, 8])
        self.assertEqual(segment["completion_ids"], [11, 12])
        self.assertEqual(segment["vllm_logprobs"], [-.1, -.2])
        self.assertEqual(segment["completion_tokens_with_bytes"], 1)

    def test_missing_or_inconsistent_native_fields_are_errors(self):
        for key, value in (("prompt_token_ids", None), ("prompt_token_ids", [7]),
                           ("usage", {"prompt_tokens": 2, "completion_tokens": 1})):
            with self.subTest(key=key, value=value), self.assertRaises(NativeCaptureError):
                native_chat_segment(dict(recorded_response(), **{key: value}))
        raw = recorded_response()
        raw["choices"][0]["logprobs"]["content"][1]["logprob"] = float("nan")
        with self.assertRaises(NativeCaptureError):
            native_chat_segment(raw)
