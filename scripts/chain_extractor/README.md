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

## Version 3 with sentence IDs

Run either input method with the frozen medium-effort settings. Pass the S run's
condition file to the W run to compare with the same conditions.

```bash
python scripts/chain_extractor/chain_extractor_v3.py /path/to/trajectory.json /private/v3-s --group S
python scripts/chain_extractor/chain_extractor_v3.py /path/to/trajectory.json /private/v3-w --group W --conditions /private/v3-s/CONDITIONS.json
```

The supplied scripts split text into numbered sentences before sending it to the local Judge.
Citation IDs are checked against the field's visible text. Narrative text is kept
when citation IDs fail. Facts and state operations require an allowed sentence ID.
The claims audit checks numeric terms and capitalized names from the cited sentences
against the return text available at that point.

Use the same output folder to resume a run with the same input and settings. Outputs
include `CHAIN.md`, `STATE.jsonl`, `CITES.jsonl`, `CLAIMS.jsonl` and `RAW.jsonl`.
W also records `STEP_CHECK.json`. Keep all outputs private.

## Version 4 with separate action and return requests

Version 4 takes an existing condition list. Save the selected question's condition
record as a private JSON file containing a `conditions` array.

```bash
python scripts/chain_extractor/chain_extractor_v4.py /path/to/trajectory.json /private/v4-s --group S --conditions /private/conditions.json
python scripts/chain_extractor/chain_extractor_v4.py /path/to/trajectory.json /private/v4-w --group W --conditions /private/conditions.json
```

S sends the action and return in separate calls. When the B response omits a
judgment for an open condition, the runner makes one follow-up and merges only
the missing judgments. W sends each step with the allowed citation ranges.
The claims audit uses terms from cited source sentences, removes question
numbers and filters capitalized names. Outputs include the same files as v3.
All results and request traces belong in private storage.

## Version 5 with answer type and checking objects

```bash
python scripts/chain_extractor/chain_extractor_v5.py /path/to/trajectory.json /private/v5
```

The stepwise runner extracts the answer type and conditions, then includes that
type in A1, A2, B and F. It records checking objects separately from candidates
and prevents a matching name from being set as the main candidate. Known visible
document IDs are filtered from numerical claim keywords.

### Judge replica layout

The proposed four-GPU layout runs one loopback vLLM server per device at TP1
(four replicas), or two TP2 servers if the single-device memory budget fails.
Use the existing MXFP4 checkpoint and vLLM 0.19.1. For each replica, select its
devices with CUDA_VISIBLE_DEVICES, bind a distinct loopback port and pass
`--tensor-parallel-size 1 --max-num-seqs 128 --max-model-len 32768
--max-num-batched-tokens 8192 --gpu-memory-utilization 0.96
--enable-prefix-caching` with the compilation config
`{"cudagraph_mode":"FULL_AND_PIECEWISE","cudagraph_capture_sizes":[1,2,4,8,16,32]}`.
Leave eager mode disabled. Keep each chain on the same replica.

The v5 trial reused the resident TP4/DP1 eager service. Its sequence limit
was 24 and prefix caching was enabled. The four-GPU quota prevented this
replica layout from starting alongside the resident allocation.

## Version 6

```bash
python scripts/chain_extractor/chain_extractor_v6.py /path/to/trajectory.json /private/v6
python -m unittest discover -s scripts/chain_extractor -v
```

The condition prompt groups source clauses by ID. The runner renders condition
text from those clauses and renders final answers from the cited answer
sentences. Candidate names use a shared normalized identity with the longest
observed spelling for display. A missing condition judgement keeps the prior
state and is listed as unjudged after the single follow-up.

### Resident Judge configuration

On four A800 devices, run one vLLM 0.19.1 server per device under the same Slurm
allocation. Assign distinct loopback ports and the native MXFP4 checkpoint.
Run this command for each replica with its own device and port:

```bash
CUDA_VISIBLE_DEVICES="$DEVICE" python -m vllm.entrypoints.openai.api_server \
  --model "$MODEL_PATH" --served-model-name gpt-oss-120b \
  --host 127.0.0.1 --port "$PORT" --tensor-parallel-size 1 \
  --generation-config vllm --gpu-memory-utilization 0.92 \
  --max-model-len 32768 --max-num-seqs 128 --max-num-batched-tokens 8192 \
  --enable-prefix-caching \
  --compilation-config '{"cudagraph_mode":"FULL_AND_PIECEWISE","cudagraph_capture_sizes":[1,2,4,8,16,32,64,128]}'
```

If one device cannot hold a replica, use two disjoint two-device groups with
tensor parallelism 2. If replica layouts fail, restore TP4 with the historical
0.88 memory limit, 131072 context, 24 sequences and 16384 batch tokens. Try TP4
with CUDA graphs first, then restore eager mode if the graph variant fails.
Set the client URL once per chain and round-robin chains across ready servers.
Run the benchmark and extraction from the allocation that hosts these
loopback services. Save outputs in private storage.

## Version 7

```bash
python scripts/chain_extractor/chain_extractor_v7.py /path/to/trajectory.json /private/v7
python -m unittest discover -s scripts/chain_extractor -v
```

V7 keeps the v6 stepwise protocol and resident service settings. Condition
groups have a lower bound tied to the number of applicable source clauses.
A2 citation records retain valid condition IDs and record rejected IDs.
Candidate aliases can use the same surname and a shorter set of name tokens.
The code preserves distinct expanded names if a short form matches more
than one of them.

The mechanism functions in `mechanisms_v7.py` operate on saved state rows,
compatible source step metadata and audited claims. They align pairwise
results by recorded call-round number. Practical sufficiency is retrospective
and reads only the trajectory's submitted answer sentences. Reference states
can be compared by passing the externally sealed reference rows. Keep all raw
trajectories, run results and reference states in private storage.
