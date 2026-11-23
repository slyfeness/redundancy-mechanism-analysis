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

## Version 2

The v2 runner uses five separate prompt files. It splits question conditions, records the start, then makes two requests per tool-call round. The first request reads the query and return. The second reads verified facts and the following thought. The runner checks citations, applies candidate and condition changes, and writes the ending. Parallel calls from one round stay in one step.

```bash
python scripts/chain_extractor/chain_extractor_v2.py /path/to/trajectory.json /private/run \
  --config scripts/chain_extractor/config_v2.json
python -m unittest discover -s scripts/chain_extractor -v
```

The supplied config uses a loopback endpoint, `gpt-oss-120b`, reasoning effort `high`, temperature 0, a fixed seed, and a 16,384-token output limit. Set the endpoint port to match the local service. Keep one writer per output directory. Resume by running the same command with the same directory. Recorded attempts are reused, and the runner checks the source, model settings and prompt hashes before resuming.

Conditions have a 70% coverage threshold, measured as the fraction of non-whitespace question characters covered after case folding and whitespace normalization. A condition request can be retried once before sentence fallback. The other phases retry JSON parse failures up to three times. The runner writes `CHAIN.md`, `STATE.jsonl`, `VERIFY.jsonl` and `RAW.jsonl` under the private output directory, along with condition and resume checkpoints.

## Stepwise and whole-trajectory extraction

Use the same medium-effort configuration and share the question condition list when comparing the two input methods. The default v2 config is still available for standalone runs.

```bash
python scripts/chain_extractor/chain_extractor_v2.py /path/to/trajectory.json /private/s \
  --config scripts/chain_extractor/config_v2_sw.json
python scripts/chain_extractor/chain_extractor_whole.py /path/to/trajectory.json /private/w \
  --config scripts/chain_extractor/config_v2_sw.json --conditions /private/s/CONDITIONS.jsonl
```

The whole-trajectory runner sends one ordered payload per run. It uses the same quote verification, state updates and Markdown rendering as the stepwise runner. Its `STEP_CHECK.json` records the returned step count and IDs. Missing or ambiguous step IDs leave the preceding state in place. They do not trigger a retry. A length-truncated response permits one attempt with the expanded token cap. Both runners retain their actual request and response bodies in `RAW.jsonl`.

Use a separate private output directory for each run. The whole-trajectory runner resumes from its recorded request attempts when the source, prompt and config match.

