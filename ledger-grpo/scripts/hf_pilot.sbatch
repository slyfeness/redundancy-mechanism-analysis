#!/bin/bash
#SBATCH --job-name=ledger-grpo-pilot
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
CONTROL=/persist_data/home/weiyu/lanyi/projects/ledger-grpo-pilot
BASE=/file_storage01/home/weiyu/lanyi
export LEDGER_PILOT_STORE="$BASE/projects/ledger-grpo-pilot"
export LEDGER_HF_BACKEND_SOURCE="$BASE/projects/browsecomp-qwen35-9b-grpo-smoke/runs/stability-tenstep-v4"
export LEDGER_PILOT_PLAN="$LEDGER_PILOT_STORE/plans/pilot-182406/PRIVATE_PLAN.json"
export LEDGER_JUDGE_KEY_FILE="$CONTROL/control/deepseek.key"
SOURCE="$CONTROL/source/20261111-v4"
if (( $# )); then
    if (( $# != 2 )); then
        printf '%s\n' 'Expected a frozen source directory and a stage settings JSON.' >&2
        exit 2
    fi
    SOURCE=$(realpath -e "$1")
    LEDGER_EVENT_PRICE_SETTINGS=$(realpath -e "$2")
    export LEDGER_EVENT_PRICE_SETTINGS
    export LEDGER_BASE_MODEL="$BASE/models/Qwen3.5-9B"
fi
export PYTHONPATH="$SOURCE/src:$SOURCE/scripts:$LEDGER_HF_BACKEND_SOURCE:$BASE/projects/browsecomp-qwen35-9b-grpo-smoke/python/fla-cuda-site"
export PYTHONPYCACHEPREFIX="$LEDGER_PILOT_STORE/runtime-pycache"
export TMPDIR="$LEDGER_PILOT_STORE/tmp"
export VLLM_RPC_BASE_PATH="$LEDGER_PILOT_STORE/i/$SLURM_JOB_ID"
export TRITON_CACHE_DIR="$LEDGER_PILOT_STORE/cache/triton"
export TORCHINDUCTOR_CACHE_DIR="$LEDGER_PILOT_STORE/cache/inductor"
export VLLM_CACHE_ROOT="$LEDGER_PILOT_STORE/cache/vllm"
export XDG_CACHE_HOME="$LEDGER_PILOT_STORE/cache/xdg"
export TORCH_HOME="$LEDGER_PILOT_STORE/cache/torch"
export CUDA_CACHE_PATH="$LEDGER_PILOT_STORE/cache/cuda"
export HF_HOME="$LEDGER_PILOT_STORE/cache/huggingface"
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=6
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
mkdir -p "$TMPDIR" "$VLLM_RPC_BASE_PATH" "$TRITON_CACHE_DIR" "$TORCHINDUCTOR_CACHE_DIR" "$VLLM_CACHE_ROOT" "$XDG_CACHE_HOME" "$TORCH_HOME" "$CUDA_CACHE_PATH" "$HF_HOME"
cd "$LEDGER_PILOT_STORE"
exec "$BASE/envs/successful_phase05_20261007/bin/python" -u "$SOURCE/scripts/hf_pilot_controller.py"
