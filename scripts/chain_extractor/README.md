# Search trajectory chain extractor

This Python 3.10+ tool turns a recorded search trajectory into a sequential JSONL chain. It uses the standard library and a local Chat Completions endpoint. The two Chinese prompt files are the byte sources for the condition and extraction prompts.

```bash
python scripts/chain_extractor/chain_extractor.py /path/to/trajectory.json /private/output \
  --config scripts/chain_extractor/config.json --run T0
python -m unittest discover -s scripts/chain_extractor -v
```

The input has `rounds` and `tool_events`. A round provides `round_id`, `actor_visible_messages`, `reasoning_content` and `content`. Tool events provide `round_id`, `dispatch_order`, `tool_call_id`, `exact_arguments` and `exact_result`. Records from the same round share a call ring. Search hits carry a `docid` and a verbatim `snippet`. The extractor reads the tool message actually present in the next sent prompt. The terminal metadata defaults to the sibling `TERMINAL.json`; supply `--terminal` to use another path. Set its `status` from the actual recorder.

Choose model, endpoint, sampling, seeds, output budget and thought truncation in `config.json`. Use `--conditions /path/to/CONDITIONS.json` to reuse a frozen list. The tool writes `CONDITIONS.json`, `INPUTS.jsonl`, `CHAIN_<run>.jsonl`, `RAW_JUDGE.jsonl`, `AUDIT.jsonl` and prompt hashes. Use a separate private output directory for each invocation that you want to retain separately.

Run the same command with the same output directory to resume. Atomic per-attempt and per-ring checkpoints reuse persisted responses and completed rings. An interrupted request whose response was never recorded may be sent again. Resume permits a changed loopback port and guards the source, parameters and prompts. Use one writer per output directory. JSON parsing failures allow one identical retry. Other request failures immediately produce a failed ring with the prior state.

Keep the entire output directory private. It contains recorded trajectory text and complete model request and response material.
