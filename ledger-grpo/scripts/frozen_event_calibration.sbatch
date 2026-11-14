#!/bin/bash
#SBATCH --job-name=ledger-frozen-calibration-audit
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=00:20:00
set -euo pipefail
umask 077
SOURCE=$(realpath -e "${1:?supply the frozen source directory}")
shift
BASE=/file_storage01/home/weiyu/lanyi
STORE="$BASE/projects/ledger-grpo-pilot"
PLAN="$STORE/reports/event-calibration-plan-182516-182710"
export PYTHONPATH="$SOURCE/src:$SOURCE/scripts:$BASE/projects/browsecomp-qwen35-9b-grpo-smoke/runs/stability-tenstep-v4"
export PYTHONPYCACHEPREFIX="$STORE/runtime-pycache" TMPDIR="$STORE/tmp" OMP_NUM_THREADS=2
cd "$STORE"
exec "$BASE/envs/successful_phase05_20261007/bin/python" -u "$SOURCE/scripts/frozen_event_calibration.py" \
  --plan "$PLAN/PLAN.json" --packet "$PLAN/BLIND_REVIEW.json" \
  --audit "$STORE/reports/event-deletion-prefixes-182516-182698.json" \
  --native-batch "$STORE/runs/pilot-182516/scored/NATIVE_BATCH.json" \
  --private-plan "$STORE/plans/pilot-182406/PRIVATE_PLAN.json" \
  --predictions "$STORE/reports/semantic-event-audit-182516-182714.json" \
  --output "$STORE/reports/frozen-calibration-audit-182516-$SLURM_JOB_ID" "$@"
