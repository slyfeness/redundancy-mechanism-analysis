#!/bin/bash
#SBATCH --job-name=m3m7-hf-smoke
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
CODE="$1"
INPUT="$2"
ROOT="$3"
BASE=/file_storage01/home/weiyu/lanyi
OUT="$ROOT/m3m7-smoke-$SLURM_JOB_ID"
PY="$BASE/envs/successful_phase05_20261007/bin/python"
ACTOR="$BASE/models/Qwen3.5-4B--851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
BACKEND="$BASE/projects/browsecomp-qwen35-9b-grpo-smoke"
export LEDGER_HF_BACKEND_SOURCE="$BACKEND/runs/stability-tenstep-v4"
export PYTHONPATH="$CODE/src:$CODE:$LEDGER_HF_BACKEND_SOURCE:$BACKEND/python/fla-cuda-site"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export TMPDIR="$OUT/tmp" TRITON_CACHE_DIR="$OUT/cache/triton" TORCHINDUCTOR_CACHE_DIR="$OUT/cache/inductor"
export XDG_CACHE_HOME="$OUT/cache/xdg" HF_HOME="$OUT/cache/huggingface" CUDA_CACHE_PATH="$OUT/cache/cuda"
mkdir -p "$TMPDIR" "$TRITON_CACHE_DIR" "$TORCHINDUCTOR_CACHE_DIR" "$XDG_CACHE_HOME" "$HF_HOME" "$CUDA_CACHE_PATH"
date -u +'%FT%TZ smoke_batch_start'
"$PY" -u -m torch.distributed.run --standalone --nproc-per-node=4 "$CODE/smoke.py" --input "$INPUT" --actor "$ACTOR" --out "$OUT"
date -u +'%FT%TZ smoke_complete'
