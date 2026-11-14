#!/bin/bash
#SBATCH --job-name=ledger-event-calibration-freeze
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
export PYTHONPATH="$SOURCE/src:$SOURCE/scripts"
export PYTHONPYCACHEPREFIX="$STORE/runtime-pycache" TMPDIR="$STORE/tmp" OMP_NUM_THREADS=2
export HF_HOME="$STORE/cache/huggingface" HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
cd "$STORE"
exec "$BASE/envs/successful_phase05_20261007/bin/python" -u "$SOURCE/scripts/freeze_event_calibration.py" \
  --run "$STORE/runs/pilot-182516" --model "$BASE/models/Qwen3.5-9B" \
  --audit "$STORE/reports/event-deletion-prefixes-182516-182698.json" \
  --split "$STORE/plans/pilot-182406/SPLIT_FREEZE.json" \
  --output "$STORE/reports/event-calibration-plan-182516-$SLURM_JOB_ID" "$@"
