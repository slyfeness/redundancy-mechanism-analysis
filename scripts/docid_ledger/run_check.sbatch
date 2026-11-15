#!/bin/bash
#SBATCH --job-name=phase1-docid-check
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=01:00:00
set -euo pipefail
umask 077

RUN_ROOT="${1:?private trial directory}"
PY="${2:?existing Python with pyarrow}"
CONFIG="${3:?frozen input configuration}"
export PYTHONDONTWRITEBYTECODE=1 TMPDIR="$RUN_ROOT"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1

date -u +'%FT%TZ check_start'
"$PY" "$RUN_ROOT/scripts/docid_ledger/check.py" --config "$CONFIG" --output "$RUN_ROOT/check-$SLURM_JOB_ID"
date -u +'%FT%TZ check_complete'
