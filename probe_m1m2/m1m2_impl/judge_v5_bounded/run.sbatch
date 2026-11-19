#!/bin/bash
#SBATCH --job-name=ledger-v5-bounded
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
CONTROL="$1"
PRIOR="$2"
RUN_NAME="${3:-judge-v5-bounded}"
ENTRY="${4:-run.py}"
JUDGE_CONTROL="${5:-$PRIOR}"
BASE=/file_storage01/home/weiyu/lanyi
ROOT="$BASE/projects/ledger-grpo-pilot/probe_m1m2/m1m2_impl"
WORK="$ROOT/$RUN_NAME-$SLURM_JOB_ID"
PY="$BASE/envs/successful_phase05_20261007/bin/python"
WEIGHTS="$BASE/models/gpt-oss-120b"
mkdir "$WORK"
test "$(sha256sum "$WEIGHTS/config.json" | cut -d' ' -f1)" = 933aeb666a3fd851133ddd7686414f369bc564c4185fb5704416550879f10566
export PYTHONPATH="$PRIOR/src" PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 OMP_NUM_THREADS=6
export HF_HOME="$WORK/cache/hf" XDG_CACHE_HOME="$WORK/cache/xdg" VLLM_CACHE_ROOT="$WORK/cache/vllm"
export TIKTOKEN_CACHE_DIR="$WORK/cache/tiktoken" TRITON_CACHE_DIR="$WORK/cache/triton"
export TORCHINDUCTOR_CACHE_DIR="$WORK/cache/inductor" CUDA_CACHE_PATH="$WORK/cache/cuda" TORCH_HOME="$WORK/cache/torch"
export TMPDIR="$BASE/lm5b-t-$SLURM_JOB_ID" VLLM_RPC_BASE_PATH="$BASE/lm5b-i-$SLURM_JOB_ID"
export VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 TOKENIZERS_PARALLELISM=false
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY OPENAI_API_KEY DEEPSEEK_API_KEY JUDGE_API_KEY
mkdir -p "$TMPDIR" "$VLLM_RPC_BASE_PATH" "$TIKTOKEN_CACHE_DIR"
if test -d "$ROOT/cache/tiktoken"; then cp -a "$ROOT/cache/tiktoken/." "$TIKTOKEN_CACHE_DIR/"; fi
date -u +'%FT%TZ batch_start'
PORT=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
URL="http://127.0.0.1:$PORT/v1"
"$PY" -m vllm.entrypoints.openai.api_server --model "$WEIGHTS" \
  --served-model-name gpt-oss-120b --host 127.0.0.1 --port "$PORT" --tensor-parallel-size 4 \
  --generation-config vllm --gpu-memory-utilization 0.88 --max-model-len 131072 --max-num-seqs 8 --enforce-eager \
  >"$WORK/server.log" 2>&1 &
JUDGE_PID=$!
trap 'kill "$JUDGE_PID" 2>/dev/null || true; wait "$JUDGE_PID" 2>/dev/null || true' EXIT
for ((attempt=0; attempt<360; attempt++)); do
    if curl --noproxy '*' -fsS --max-time 4 "$URL/models" >"$WORK/models.json" 2>/dev/null; then break; fi
    kill -0 "$JUDGE_PID"
    sleep 5
done
test -s "$WORK/models.json"
date -u +'%FT%TZ judge_ready'
"$PY" "$CONTROL/$ENTRY" --root "$ROOT" --v4-control "$JUDGE_CONTROL" --out "$WORK/results" --url "$URL"
date -u +'%FT%TZ complete'
