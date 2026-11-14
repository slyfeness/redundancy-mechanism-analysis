# Ledger-GRPO real-runtime pilot, 2026-11-11

The user requested the tested final generation configuration from the chat
“设计论文复现项目框架”, an end-to-end run, and live RL diagnostics.

## Isolation and frozen inputs

Reuse Qwen3.5-9B and the actual `stability-tenstep-v4` generation implementation
that ran job 181915 (8 updates; failure during ninth rollout; no final freeze of
the ten-step experiment). Preserve the old experiment, its checkpoints and code.
Do not resume its interrupted recovery. The newer local recovery source is not
the verified execution source.

Actor: BF16, four TP1 resident instances, thinking, T=1, top-p=1, top-k=0,
65536 context, 256 guard headroom, 10000 maximum completion tokens per call,
20 actor calls, prefix cache and CUDA graphs, max 32 requests per actor.
Four-card requests use gre/professors, one node/task, 24 CPUs, 384G, 48h;
no requested node/card model. Runtime hardware compatibility must be checked.

## Execution order

1. CPU Slurm: audit the existing eight completed batches for strict complete
   eight-member groups and learning signal. All retained/censored costs reported.
2. CPU Slurm: bounded process-judge preflight, one complete P0 group (at most a
   second group if needed for diagnosis), four concurrent trajectories. Judge
   is the explicitly authorized official DeepSeek API using the retained key.
   Do not expose key, gold or future evidence to process judging. Historical
   data is an engineering calibration sample, not a held-out result.
3. Verify exact native call → merged span → policy token → advantage alignment,
   effective global token denominator, and nonzero method-vs-control signal.
4. After a training-eligible batch: independent matched outcome/ledger pilot,
   same starting model and schedules. If process QA turns the entire batch into
   outcome fallback and both token objectives/masks are exactly equal, execute
   only one equivalent update for end-to-end engineering verification and label
   it explicitly as fallback, not evidence of process-reward efficacy. Both use
   sample-standardized group advantages, global token mean, existing capped
   TIS=2, lr=1e-6, clip-grad=1, KL=0 and one step per complete batch.
5. Real training requires fresh on-policy data after each arm's update. Never
   train P0 from later historical policy rollouts. Use a separately frozen
   evaluation set excluding all old 160 training questions and this pilot's
   training selection. Single-seed pilot estimates are exploratory.

Strict QA remains unchanged. The user explicitly approved the versioned
`budget_failure_policy=outcome_only` update on 2026-11-11: fully recorded budget
failures keep outcome=0 training credit; their entire group loses process credit.
They remain complete=false. Unknown/tool failures and incomplete recordings do
not qualify. No shrinking groups to survivors or optimizer call on all-zero
effective masks/advantages. Missing process signal is recorded, not described
as a successful method comparison.

## Storage, monitoring, termination

All computation (including audits, hashing and data conversion) via Slurm.
Control/scripts/secrets: /persist_data/home/weiyu/lanyi/projects/ledger-grpo-pilot.
Data, logs, caches, reports, models and checkpoints: /file_storage01/home/weiyu/lanyi.
No new environments or large installs. No change to other jobs.

Monitor queue, service readiness, model compute, process QA, effective groups,
advantage changes, outcome/grounding/redundancy/cost, optimizer commits,
checkpoint persistence and actor publication separately. Keep unknowns null.
No scheduled automation. Follow submitted work to terminal status.

API labels do not establish calibrated accuracy. Training loss, shorter output
and historical rewards do not establish a task-performance improvement.
