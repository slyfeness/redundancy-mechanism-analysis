# Credit v2.1 integration

Credit v2.1 is an optional branch of the existing recorder → `hf_pilot_train.py`
→ native HF/FSDP worker. The legacy scoring path remains available. Importing or
preparing credit does not start a model, construct an HTTP client, or download
anything. Synthetic tests contain no dataset examples.

## Modules

| Module under `ledger_grpo.credit` | Responsibility |
| --- | --- |
| `config` | Reference parameters, independent experiment switches, preset validation |
| `schema` | Model-call units, trajectories, same-question groups, v13.4 field validation |
| `ledger` | Reference v13.4 ledger program with its original labels |
| `providers` | Recorded, null, mock and explicit live ledger sources |
| `judge`, `pipeline`, `pipeline_checked`, `pipeline_rules` | Replaceable replay/HTTP transport and frozen v13.4 request pipeline |
| `events` | Reference contribution, responsibility and diagnostic events |
| `utility` | Outcome/progress/waste utilities and leave-one-out advantages |
| `roles` | Pure contribution, pure responsibility and protected/unknown roles |
| `allocate` | Reference capped allocation, uniform/clear-only controls and stratified shuffle |
| `group` | Whole-group utility and unit credit; low-confidence/mismatch protection |
| `tokens` | Merge parallel tools by model call and write exact native-token advantages |
| `training` | Whole-batch preparation, fixed normalization, PPO, group correction and auxiliary NLL |
| `process_sup` | Gated verified-decision NLL and token-weighted zero-sum signals |
| `sampling` | Deterministic whole-group sampling and loss-level correction |
| `continuation` | Trigger, branch choice, local advantages and review-selection pure functions |
| `metrics` | Content-free result, group, event, allocation, policy and module summaries |
| `datasets` | BC-Plus recorder adapter and explicit future dataset interfaces |

## Exact token contract

One unit is one generated model call. Its entire generated interval, including
reasoning and all parallel tool-call syntax, belongs to that unit. All returned
tool tokens are counted in cost; prompt and observation positions have loss mask
zero. Unit `t` corresponds to tool-call record `t`; a final model call that
formally answers or declines without tools is `F`. Processing-event attribution is performed by the reference event
extractor, not by shifting token positions in the trainer.

The recorder's `native_turn_layout` provides the exact probability-ratio axis.
Each generated position must have exactly one owner. Missing ownership,
overlaps, or ownership of an observation/prompt token raise an error. Split M1
stages with the same `model_call_index` merge their ranges and parallel returns.
If ledger/model-call counts differ, all ambiguous tool units are protected as K
and counted; they retain the trajectory advantage. Independently detected
per-unit mismatches can be supplied in `Trajectory.metadata['unmatched_units']`;
this protects only those units. An unfinished or empty terminal model call is
retained as K, counted in generated-token cost, and does not count as a tool call,
F, or a formal submission. The training token shares use
actual generated-token counts. Costs use `(generated + all returns) / 3146`;
`F` has generated cost only. Reference-consistency tests separately use the
reference character-count loader and `costs=None`.

## Creating a score payload for the existing worker

The caller supplies training-only recorder data and independently established
outcomes. `BCPlusAdapter` requires a recorded `outcome` or an explicitly supplied
frozen scorer. It never silently substitutes exact match for semantic grading.
`normalized_exact_match` is an explicit synthetic/test helper only. Gold and
outcomes are program-side data, and are never serialized wholesale into Judge
requests.

```python
import os
from pathlib import Path
import torch

from ledger_grpo.credit.config import CreditConfig
from ledger_grpo.credit.datasets import BCPlusAdapter
from ledger_grpo.credit.providers import RecordedLedgerProvider
from ledger_grpo.credit.schema import Group
from ledger_grpo.credit.training import make_credit_score_payload

# parsed_m1_rows: existing parse_stages results augmented with recorded outcome.
# Each result contains `native`, `stages`, `outcome`, and a rollout index.
adapter = BCPlusAdapter()
trajectories = [
    adapter.parse_model_calls(row, gold=program_gold[row['native']['query_id']],
                              rollout=row['rollout'])
    for row in parsed_m1_rows
]
# Group each production question's eight rollouts together; do not standardize U.
groups = [Group(qid, [tr for tr in trajectories if tr.qid == qid])
          for qid in dict.fromkeys(tr.qid for tr in trajectories)]
assert all(len(group) == 8 for group in groups)
config = CreditConfig.from_preset('C_W')
provider = RecordedLedgerProvider(Path(os.environ['CREDIT_STATE_ROOT']))
payload = make_credit_score_payload(
    Path(os.environ['NATIVE_BATCH']), groups, config,
    provider=provider,
    max_generated_tokens=int(os.environ['MAX_GENERATED_TOKENS']),
    training_step=int(os.environ.get('TRAINING_STEP', '0')),
    sampling_seed=2026112501,
)
torch.save(payload, Path(os.environ['CREDIT_SCORES']))
```

`make_credit_score_payload` materializes only selected groups through the supplied
provider and validates the complete native mapping before returning. It binds
the native batch hash and policy snapshot. The payload contains program-side
ledgers and gold, so it belongs in private storage. No advantages need to be
calculated manually. Baselines A/A_eff do not request ledgers.

Use the existing authorized worker invocation with this score file:

```sh
PYTHONPATH=src:scripts torchrun --nproc_per_node=4 scripts/hf_pilot_train.py \
  --native-batch "$NATIVE_BATCH" --scores "$CREDIT_SCORES" \
  --output-root "$UPDATE_ROOT" --snapshot-dir "$SNAPSHOT_ROOT" \
  --publication-id "$PUBLICATION_ID" --ppo-epochs 1
```

The existing Slurm/backend requirements still apply. This command is an example,
not authorization to launch an experiment. For offline tests, call
`prepare_credit_native_records(native_rows, groups, provider, config,
max_generated_tokens=...)`, then the worker's optimizer-free
`freeze_native_old_logprobs(prepared, model, collective)` followed by
`record_loss(record, prepared, model, collective)` or `run_ppo_updates`.

## Loss and batch lifetime

Preparation freezes unit advantages, baseline advantages, group-selection
decisions and auxiliary masks once per rollout batch. All minibatches consume
these tensors unchanged. The default denominator is the number of trajectories
in that batch times the configured per-trajectory generated-token limit.
`normalization='batch_token_mean'` is an explicit debug option. Per-trajectory
or per-sequence averaging raises an error in every credit mode. Group standard
deviation normalization is never applied.

The native worker defaults to one update per fresh batch and supports explicit
`--ppo-epochs N` using one initial-policy cache for all N optimizer steps. It
keeps the existing detached sampling-importance cap of 2. PPO epsilon is 0.2, learning rate
is 1e-6 and the existing KL coefficient is zero; no second KL term is added.
The initial old-policy forward runs without gradients before any update. Its
cached probabilities, native coordinates, sampling probabilities and credit
targets are fingerprinted. Every subsequent loss verifies the fingerprint and
uses the same old probabilities and advantages. `run_ppo_updates` performs the
actual repeated optimizer steps and the CLI persists/publishes only the final
step. A partially consumed batch cannot restart automatically. For action
microbatches, `slice_credit_native_record(record, start, stop)` retains the full
causal context and slices all frozen action-axis tensors together.

Offline smoke data lacking sampled logprobs may explicitly use
`freeze_native_old_logprobs(..., use_old_as_sampled=True)`. The receipt labels
those probabilities `initial_hf_smoke_surrogate`; this option does not validate
real sampling-importance correction and is not enabled by the training CLI.

Sampling correction combines two separately clipped losses:
`L0 + selected / q * (L_full - L0)`. It does not interpolate advantages before
clipping. Auxiliary NLL is included in `L_full` with the same denominator and
group correction. Auxiliary-only batches can update, and padded FSDP records
have both policy and auxiliary masks zero. The zero-sum signal is added only
after its whole-group eligibility check. The training receipt includes prepared
credit metrics and measured entropy, clipping, gradient norm and auxiliary loss;
unmeasured KL is `null`, not an invented measurement.

## Offline scope and extension points

Recorded and replay providers are complete; the HTTP client requires explicit
configuration and enablement. Frozen prompts are checked by hash. Live requests
are not part of the offline tests. `Group(..., allow_mixed_qids=True)` exists only
for explicitly marked mechanism smoke groups; production groups enforce one
question and unique rollouts. Cross-question smoke groups should carry their
already recorded ledgers rather than asking a provider to share conditions.

DRACO raises `NotImplementedError`. DeepSearch-World, SAGE and SciCode adapters
are explicit stubs. SAGE submission maps to F; SciCode progress will track the
first verification of each requirement. Continuation has pure decision and
comparison functions, while real prefix resampling and main-loss integration
remain TODO. Real-data consistency, replay, alignment and model smoke artifacts
are maintained outside this public training repository.

Synthetic verification commands (using an existing environment):

```sh
PYTHONPATH=src:scripts python -m pytest tests
PYTHONPATH=src:scripts python -m unittest discover -s tests -p 'test_credit*.py'
```
