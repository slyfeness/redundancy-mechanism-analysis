"""Collect the served token IDs and action probabilities from vLLM chat."""

import math


class NativeCaptureError(ValueError):
    """The response cannot be used as a native policy segment."""


def native_chat_request(request):
    """Add non-streaming capture fields while preserving model sampling."""
    if request.get("stream", False) is not False or request.get("n", 1) != 1:
        raise NativeCaptureError("native capture requires one non-streaming completion")
    return dict(request, stream=False, return_token_ids=True, logprobs=True)


def native_chat_segment(response):
    """Return original IDs and selected-token logprobs from one response."""
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise NativeCaptureError("expected a single recorded choice")
    choice = choices[0]
    prompt, completion = response.get("prompt_token_ids"), choice.get("token_ids")
    usage = response.get("usage")
    if not isinstance(usage, dict):
        raise NativeCaptureError("missing serving token usage")
    for name, tokens in (("prompt_tokens", prompt), ("completion_tokens", completion)):
        count = usage.get(name)
        if (not isinstance(tokens, list) or type(count) is not int or count != len(tokens)
                or any(type(token) is not int or token < 0 for token in tokens)):
            raise NativeCaptureError(f"missing or inconsistent native {name}")
    if not prompt:
        raise NativeCaptureError("native prompt IDs are empty")
    logprobs = choice.get("logprobs")
    entries = logprobs.get("content") if isinstance(logprobs, dict) else None
    if not isinstance(entries, list) or len(entries) != len(completion):
        raise NativeCaptureError("selected-token probabilities do not cover the completion")
    values, with_bytes = [], 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise NativeCaptureError("invalid selected-token probability entry")
        logprob, chunk = entry.get("logprob"), entry.get("bytes")
        if type(logprob) not in (float, int) or not math.isfinite(logprob) or logprob > 0:
            raise NativeCaptureError("invalid selected-token logprob")
        if chunk is not None and (not isinstance(chunk, list)
                                  or any(type(byte) is not int or not 0 <= byte <= 255 for byte in chunk)):
            raise NativeCaptureError("invalid selected-token byte record")
        values.append(logprob)
        with_bytes += bool(chunk)
    return {"prompt_ids": prompt, "completion_ids": completion, "vllm_logprobs": values,
            "completion_tokens_with_bytes": with_bytes}


def capture_status(response):
    """Record why a round can or cannot provide native policy tokens."""
    try:
        segment = native_chat_segment(response)
    except NativeCaptureError as error:
        return {"valid": False, "error": str(error)}
    return {"valid": True, "prompt_tokens": len(segment["prompt_ids"]),
            "completion_tokens": len(segment["completion_ids"]),
            "completion_tokens_with_bytes": segment["completion_tokens_with_bytes"]}
