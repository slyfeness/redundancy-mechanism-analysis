#!/bin/bash
#SBATCH --job-name=ledger-sampler-process-check
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
export PYTHONPATH="$SOURCE/src:$SOURCE/scripts:$SOURCE/tests"
export PYTHONPYCACHEPREFIX="$STORE/runtime-pycache" TMPDIR="$STORE/tmp" OMP_NUM_THREADS=2
export HF_HOME="$STORE/cache/huggingface" HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
cd "$STORE"
exec "$BASE/envs/successful_phase05_20261007/bin/python" -u "$SOURCE/scripts/verify_sampler_process.py" \
  --model "$BASE/models/Qwen3.5-9B" --scratch "$STORE/tmp" \
  --output "$STORE/reports/sampler-process-verification-$SLURM_JOB_ID.json"
