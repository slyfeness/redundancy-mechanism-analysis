#!/bin/bash
#SBATCH --job-name=ledger-regrade
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
set -euo pipefail
umask 077
BASE=/file_storage01/home/weiyu/lanyi
CONTROL=/persist_data/home/weiyu/lanyi/projects/ledger-grpo-pilot
STORE="$BASE/projects/ledger-grpo-pilot"
SOURCE="$CONTROL/source/20261111-event-regrade-v3"
PYTHON="$BASE/envs/successful_phase05_20261007/bin/python"
export PYTHONPATH="$SOURCE/src:$SOURCE/scripts:$BASE/projects/browsecomp-qwen35-9b-grpo-smoke/runs/stability-tenstep-v4"
export PYTHONPYCACHEPREFIX="$STORE/runtime-pycache" TMPDIR="$STORE/tmp"
export HF_HOME="$STORE/cache/huggingface" HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 OMP_NUM_THREADS=2
MODE="$1"
shift
KEY="$CONTROL/control/deepseek.key"
ARGS=()
case "$MODE" in
  check) ARGS=(--dry-run) ;;
  apply) ARGS=(--key-file "$KEY") ;;
  balance)
    cd "$STORE"
    exec "$PYTHON" -c 'from pathlib import Path; from regrade_pilot import _balance_available; import sys; print("deepseek_balance_available", _balance_available(Path(sys.argv[1]).read_text().strip()))' "$KEY"
    ;;
  *) exit 2 ;;
esac
cd "$STORE"
exec "$PYTHON" -u "$SOURCE/scripts/regrade_pilot.py" \
  --run "$STORE/runs/pilot-182516" \
  --plan "$STORE/plans/pilot-182406/PRIVATE_PLAN.json" \
  --output "$STORE/reports/event-regrade-182516/$SLURM_JOB_ID" \
  "${ARGS[@]}" "$@"
