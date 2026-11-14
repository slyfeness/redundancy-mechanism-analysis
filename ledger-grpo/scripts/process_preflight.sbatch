#!/bin/bash
#SBATCH --job-name=ledger-process-preflight
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
set +x
set -euo pipefail
umask 077
CONTROL=/persist_data/home/weiyu/lanyi/projects/ledger-grpo-pilot
STORE=/file_storage01/home/weiyu/lanyi/projects/ledger-grpo-pilot
SOURCE="$CONTROL/source/20261111-v1"
export PYTHONPATH="$SOURCE/src"
export PYTHONPYCACHEPREFIX="$STORE/runtime-pycache"
export OMP_NUM_THREADS=1 HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1
cd "$SOURCE"
exec /file_storage01/home/weiyu/lanyi/envs/successful_phase05_20261007/bin/python -u scripts/process_preflight.py \
 --rollout /file_storage01/home/weiyu/lanyi/projects/browsecomp-qwen35-9b-grpo-smoke/runs/grpo-stability-181915/step-01/rollout-1 \
 --output "$STORE/preflight/process-$SLURM_JOB_ID" \
 --key-file "$CONTROL/control/deepseek.key" --groups 1
