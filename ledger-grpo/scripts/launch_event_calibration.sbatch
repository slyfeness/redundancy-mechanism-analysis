#!/bin/bash
#SBATCH --job-name=ledger-event-continuation
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=24
#SBATCH --mem=384G
#SBATCH --time=48:00:00
set -euo pipefail
umask 077
SOURCE=$(realpath -e "${1:?supply the frozen calibration source directory}")
shift
BASE=/file_storage01/home/weiyu/lanyi
export LEDGER_PILOT_STORE="$BASE/projects/ledger-grpo-pilot"
export LEDGER_HF_BACKEND_SOURCE="$BASE/projects/browsecomp-qwen35-9b-grpo-smoke/runs/stability-tenstep-v4"
export PYTHONPATH="$SOURCE/src:$SOURCE/scripts:$LEDGER_HF_BACKEND_SOURCE:$BASE/projects/browsecomp-qwen35-9b-grpo-smoke/python/fla-cuda-site"
export PYTHONPYCACHEPREFIX="$LEDGER_PILOT_STORE/runtime-pycache" TMPDIR="$LEDGER_PILOT_STORE/tmp"
export VLLM_RPC_BASE_PATH="$LEDGER_PILOT_STORE/i/$SLURM_JOB_ID"
export TRITON_CACHE_DIR="$LEDGER_PILOT_STORE/cache/triton" TORCHINDUCTOR_CACHE_DIR="$LEDGER_PILOT_STORE/cache/inductor"
export VLLM_CACHE_ROOT="$LEDGER_PILOT_STORE/cache/vllm" XDG_CACHE_HOME="$LEDGER_PILOT_STORE/cache/xdg"
export TORCH_HOME="$LEDGER_PILOT_STORE/cache/torch" CUDA_CACHE_PATH="$LEDGER_PILOT_STORE/cache/cuda"
export HF_HOME="$LEDGER_PILOT_STORE/cache/huggingface" HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=6 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
mkdir -p "$TMPDIR" "$VLLM_RPC_BASE_PATH" "$TRITON_CACHE_DIR" "$TORCHINDUCTOR_CACHE_DIR" "$VLLM_CACHE_ROOT" \
  "$XDG_CACHE_HOME" "$TORCH_HOME" "$CUDA_CACHE_PATH" "$HF_HOME"
cd "$LEDGER_PILOT_STORE"
exec "$BASE/envs/successful_phase05_20261007/bin/python" -u "$SOURCE/scripts/launch_event_calibration.py" \
  --rollout "$LEDGER_PILOT_STORE/runs/pilot-182516/train-P0" --model "$BASE/models/Qwen3.5-9B" \
  --plan "$LEDGER_PILOT_STORE/reports/event-calibration-plan-182516-182710/PLAN.json" \
  --audit "$LEDGER_PILOT_STORE/reports/event-deletion-prefixes-182516-182698.json" \
  --output "$LEDGER_PILOT_STORE/runs/event-calibration-$SLURM_JOB_ID" "$@"
