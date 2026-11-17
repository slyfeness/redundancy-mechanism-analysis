#!/bin/bash
#SBATCH --job-name=actor-judge-coexist
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=24
#SBATCH --mem=384G
#SBATCH --time=48:00:00
set +x
set -euo pipefail
umask 077
SOURCE="${1:?source path}"
CONFIG="${2:?trial configuration}"
BULK="${3:?bulk storage path}"
ACTOR_PY="${4:?actor Python}"
BACKEND="${5:?frozen FSDP/Actor backend}"
SITE=/file_storage01/home/weiyu/lanyi/projects/browsecomp-qwen35-9b-grpo-smoke/python/fla-cuda-site
OUTPUT="$BULK/coexist-$SLURM_JOB_ID"
mkdir -m 700 "$OUTPUT"
cd "$OUTPUT"
export TZ=UTC
export LEDGER_HF_BACKEND_SOURCE="$BACKEND"
export LEDGER_BASE_MODEL=/file_storage01/home/weiyu/lanyi/models/Qwen3.5-9B
export LEDGER_PILOT_STORE="$BULK"
export PYTHONPATH="$SOURCE/src:$SOURCE/ledger-grpo/src:$SOURCE/ledger-grpo/scripts:$BACKEND:$SITE"
# Keep IPC under the platform's Unix socket length limit and all writes under the private bulk root.
export TMPDIR="$BULK/t/$SLURM_JOB_ID" VLLM_RPC_BASE_PATH="$BULK/i/$SLURM_JOB_ID"
export PYTHONPYCACHEPREFIX="$OUTPUT/pycache" TRITON_CACHE_DIR="$OUTPUT/cache/triton"
export TORCHINDUCTOR_CACHE_DIR="$OUTPUT/cache/inductor" VLLM_CACHE_ROOT="$OUTPUT/cache/vllm"
export XDG_CACHE_HOME="$OUTPUT/cache/xdg" TORCH_HOME="$OUTPUT/cache/torch"
export CUDA_CACHE_PATH="$OUTPUT/cache/cuda" HF_HOME="$OUTPUT/cache/hf"
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=6 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy JUDGE_API_KEY DEEPSEEK_API_KEY OPENAI_API_KEY
mkdir -p "$TMPDIR" "$VLLM_RPC_BASE_PATH" "$TRITON_CACHE_DIR" "$TORCHINDUCTOR_CACHE_DIR" \
  "$VLLM_CACHE_ROOT" "$XDG_CACHE_HOME" "$TORCH_HOME" "$CUDA_CACHE_PATH" "$HF_HOME"
test "$(( ${#VLLM_RPC_BASE_PATH} + 37 ))" -le 107
cp "$CONFIG" "$OUTPUT/config.json"
nvidia-smi > "$OUTPUT/nvidia-smi-start.log"
date -u +'%FT%TZ batch_start'
"$ACTOR_PY" -u "$SOURCE/ledger-grpo/scripts/coexist_controller.py" "$OUTPUT/config.json" "$OUTPUT"
"$ACTOR_PY" -u "$SOURCE/ledger-grpo/scripts/coexist_report.py" "$OUTPUT" /file_storage01/home/weiyu/lanyi/projects/ledger-grpo-pilot/runs/pilot-182516
date -u +'%FT%TZ measurement_complete'
