
# shellcheck shell=bash
BASE=/file_storage01/home/weiyu/lanyi
PY="$BASE/envs/successful_phase05_20261007/bin/python"
export PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false
export HF_HOME="$1/cache/hf" XDG_CACHE_HOME="$1/cache/xdg" VLLM_CACHE_ROOT="$1/cache/vllm"
export TIKTOKEN_CACHE_DIR="$1/cache/tiktoken" TRITON_CACHE_DIR="$1/cache/triton"
export TORCHINDUCTOR_CACHE_DIR="$1/cache/inductor" CUDA_CACHE_PATH="$1/cache/cuda" TORCH_HOME="$1/cache/torch"
export TMPDIR="$BASE/m2v61-$SLURM_JOB_ID-t" VLLM_RPC_BASE_PATH="$BASE/m2v61-$SLURM_JOB_ID-v"
export VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY OPENAI_API_KEY DEEPSEEK_API_KEY JUDGE_API_KEY
mkdir -p "$TMPDIR" "$VLLM_RPC_BASE_PATH" "$TIKTOKEN_CACHE_DIR"
CACHE="$(dirname "$1")/cache/tiktoken"
if test -d "$CACHE"; then cp -a "$CACHE/." "$TIKTOKEN_CACHE_DIR/"; fi
TEVATRON=(/persist_data/home/weiyu/lanyi/projects/*/third_party/tevatron_phase05/src)
test "${#TEVATRON[@]}" -eq 1
export PYTHONPATH="${TEVATRON[0]}${PYTHONPATH:+:$PYTHONPATH}"
