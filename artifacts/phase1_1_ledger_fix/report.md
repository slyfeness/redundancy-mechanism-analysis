# Phase 1.1 Ledger validity repair — engineering report

## Status

`ENGINEERING_PASS / JUDGE_PENDING_HUMAN_REVIEW`

The code and synthetic/regression protocol are complete and verified locally. The required real-data small-sample and full development replay were **not run**: the frozen BrowseComp source is controlled by another project whose active `AGENTS.md` permits only MuSiQue Phase 0.7 and explicitly disallows BrowseComp/Judge work. No override was assumed.

## Implemented fixes

- `final_candidate` now uses a validated exact character span and a required submission anchor. Repeated answer text has no first/last-occurrence fallback.
- `evidence_update` now requests validated offsets. Rows are checked independently: a valid row remains usable when another row is rejected.
- Rejected rows retain candidate/constraint/state scope. A rejected refutation or conflict becomes `unresolved_evidence_risk`; unscoped failures remain global risk. Such uncertainty cannot silently become a measured zero gain.
- `summarize_trajectory` only blocks `g` for global risks or risks relevant to the submitted candidate's necessary constraints. Unrelated failures are retained but no longer globally poison a demonstrably independent candidate.
- `action_target` supports `gap_id` and `evidence_basis`. An open exploration can be represented without manufacturing a candidate×constraint R1 target.
- `judge_stage` emits a structured `r1_funnel` result. It distinguishes not-invoked, actual low-confidence, negative, positive, and error outcomes, eliminating the former false "low confidence" explanation for uncalled checks.
- The runtime JSON protocol, prompts and packaged record schema were updated together. Legacy uniquely located quotes still parse; ambiguous legacy quotes do not.

## Frozen baseline, not a new result

The immutable diagnostic summary records 400 trajectories, 5,114 tool events, 810 quote failures, 15 real R1 checks, 4 real low-confidence calls, 53 incorrectly recorded low-confidence cases, and 9 valid `g` values (4 correct trajectories). These are baseline observations only. `before_after_metrics.json` records each Phase 1.1 real-data metric as `null`, rather than inventing an improvement.

## Test evidence

Baseline: 66 tests passed. Fixed tree: 75 tests passed. The added regression coverage includes repeated final candidates, ambiguous two-answer finals, repeated/malformed evidence, valid-plus-invalid batches, potential rejected refutations, scoped and global uncertainty, open exploration without an R1 target, no automatic entity-name merging, R1/R2b priority, and future-information exclusion. See `regression_results.json` and `semantic_review_cases.jsonl`.

## Safety / remaining review

- No natural trajectory, old output, old cache, token coordinate, reward equation, R1/R2b/R2a definition, or training result was modified.
- No local or remote model request, actor generation, deletion continuation, GRPO update, or Slurm job was started.
- Entity aliases remain conservative: name similarity never merges evidence. A future alias protocol must be separately designed with explicit textual identity evidence and independently reviewed.
- The new prompt contract needs real cached/local-Judge validation before any claimed improvement in candidate extraction, evidence grounding, R1 coverage, or `g` coverage.
- No Judge label is approved for training. `formal_training_usable` remains false.
