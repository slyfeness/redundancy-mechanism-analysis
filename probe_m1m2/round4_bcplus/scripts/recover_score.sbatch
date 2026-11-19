#!/bin/bash
#SBATCH --job-name=bcplus-r4-judge-retry
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
date -u +'%FT%TZ batch_start'
SOURCE="${1:?control}"
SELECTION="${2:?frozen selection}"
RUN="${3:?frozen rollout}"
OUT="${4:?run bulk directory}/retry-$SLURM_JOB_ID"
BASE=/file_storage01/home/weiyu/lanyi
LEDGER=/persist_data/home/weiyu/lanyi/projects/ledger-grpo-pilot/source/20261112-calibration-workflow-v2
PY="$BASE/envs/successful_phase05_20261007/bin/python"
export PYTHONPATH="$LEDGER/src"
export TMPDIR="$BASE/lcr4/t" VLLM_RPC_BASE_PATH="$BASE/lcr4/i"
export PYTHONDONTWRITEBYTECODE=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=6
export HF_HOME="$OUT/cache/hf" HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export VLLM_CACHE_ROOT="$OUT/cache/vllm" XDG_CACHE_HOME="$OUT/cache/xdg"
export TRITON_CACHE_DIR="$OUT/cache/triton" TORCHINDUCTOR_CACHE_DIR="$OUT/cache/inductor"
export CUDA_CACHE_PATH="$OUT/cache/cuda" TORCH_HOME="$OUT/cache/torch" TIKTOKEN_CACHE_DIR="$OUT/cache/tiktoken"
export VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True TZ=UTC
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY OPENAI_API_KEY DEEPSEEK_API_KEY JUDGE_API_KEY
mkdir -p "$TIKTOKEN_CACHE_DIR"
mkdir "$OUT/verdicts"
PORT=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
URL="http://127.0.0.1:$PORT/v1"
MODEL=gpt-oss-120b
"$PY" -m vllm.entrypoints.openai.api_server --model "$BASE/models/$MODEL" \
    --served-model-name "$MODEL" --host 127.0.0.1 --port "$PORT" --tensor-parallel-size 4 \
    --generation-config vllm --gpu-memory-utilization 0.88 --max-model-len 131072 --max-num-seqs 4 --enforce-eager \
    > "$OUT/JUDGE_SERVER.log" 2>&1 &
JUDGE_PID=$!
trap 'kill "$JUDGE_PID" 2>/dev/null || true; wait "$JUDGE_PID" 2>/dev/null || true' EXIT
for ((i=0; i<360; i++)); do
    if curl --noproxy '*' -fsS --max-time 4 "$URL/models" > "$OUT/JUDGE_MODELS.json" 2>/dev/null; then break; fi
    kill -0 "$JUDGE_PID"
    sleep 5
done
test -s "$OUT/JUDGE_MODELS.json"
date -u +'%FT%TZ judge_ready'
"$PY" -u "$SOURCE/recover_score.py" "$RUN" "$SELECTION" "$OUT/verdicts" "$URL" "$MODEL" "${5:-60}" "${6:-1}"
date -u +'%FT%TZ retry_complete'
