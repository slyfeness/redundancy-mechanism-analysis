# Phase 1.1 engineering reproduction

This directory contains engineering evidence only. It intentionally does not claim a new real-data replay.

## Baseline

```powershell
& 'C:\Users\24413\AppData\Local\Temp\codex-phase1-ledger-venv\Scripts\python.exe' -m pytest -q
```

Before the changes this returned `66 passed in 2.68s` on commit `8c7573f57c93ff76223366d885481c64d4836197`.

## Fixed implementation regression suite

```powershell
& 'C:\Users\24413\AppData\Local\Temp\codex-phase1-ledger-venv\Scripts\python.exe' -m pytest -q
git diff --check
```

The recorded result is `75 passed in 2.16s` and a clean whitespace check.

## Controlled real-data replay (not run)

The frozen raw BrowseComp records and old private cache remain at the controlled server location identified in the baseline `input_manifest.json`. The current `AGENTS.md` for the source project authorizes only MuSiQue Phase 0.7 and prohibits BrowseComp/Judge work. A later authorized replay must:

1. create a new output directory; never reuse `run-184780` or diagnosis output;
2. copy the baseline config, use the Phase 1.1 source and prompts, and record the new code/prompt/config hashes;
3. start with a declared small development sample and cache every local Judge request separately;
4. run all development trajectories only after sample review;
5. generate before/after metrics and independent human-review packets;
6. retain `formal_training_usable=false` and perform no optimizer update.
