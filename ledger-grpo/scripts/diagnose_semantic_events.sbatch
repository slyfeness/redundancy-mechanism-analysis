#!/bin/bash
#SBATCH --job-name=ledger-semantic-event-audit
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
BASE=/file_storage01/home/weiyu/lanyi
STORE="$BASE/projects/ledger-grpo-pilot"
export PYTHONPATH="$SOURCE/src:$SOURCE/scripts"
export PYTHONPYCACHEPREFIX="$STORE/runtime-pycache" TMPDIR="$STORE/tmp" OMP_NUM_THREADS=2
cd "$STORE"
exec "$BASE/envs/successful_phase05_20261007/bin/python" -u "$SOURCE/scripts/diagnose_semantic_events.py" \
  --run "$STORE/runs/pilot-182516" --audit "$STORE/reports/event-deletion-prefixes-182516-182698.json" \
  --coordinates "$STORE/reports/tool-coordinates-182516-served.json" \
  --plan "$STORE/reports/event-calibration-plan-182516-182710/PLAN.json" \
  --output "$STORE/reports/semantic-event-audit-182516-$SLURM_JOB_ID.json"
