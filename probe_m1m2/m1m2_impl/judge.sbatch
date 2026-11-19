#!/bin/bash
#SBATCH --job-name=ledger-m2-judge
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
BASE=/file_storage01/home/weiyu/lanyi
STORE="$BASE/projects/ledger-grpo-pilot/probe_m1m2"
PRIVATE="$STORE/m1m2_impl"
date -u +'%FT%TZ batch_start'
ENV="$BASE/envs/successful_phase05_20261007"
PY="$ENV/bin/python"
MODEL=gpt-oss-120b
WEIGHTS="$BASE/models/$MODEL"
export PYTHONPATH="$1/src"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1
export HF_HOME="$PRIVATE/cache/huggingface" XDG_CACHE_HOME="$PRIVATE/cache/xdg"
export VLLM_CACHE_ROOT="$PRIVATE/cache/vllm" TIKTOKEN_CACHE_DIR="$PRIVATE/cache/tiktoken"
export TRITON_CACHE_DIR="$PRIVATE/cache/triton" TMPDIR="$BASE/lcm12/t"
export VLLM_RPC_BASE_PATH="$BASE/lcm12/i" VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1
export TORCHINDUCTOR_CACHE_DIR="$PRIVATE/cache/inductor" CUDA_CACHE_PATH="$PRIVATE/cache/cuda"
export TORCH_HOME="$PRIVATE/cache/torch" TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=6
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY OPENAI_API_KEY DEEPSEEK_API_KEY JUDGE_API_KEY
mkdir -p "$TMPDIR" "$VLLM_RPC_BASE_PATH" "$TIKTOKEN_CACHE_DIR"
JUDGE_JOB="$PRIVATE/judge-$SLURM_JOB_ID"
mkdir "$JUDGE_JOB"
PORT=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
URL="http://127.0.0.1:$PORT/v1"
"$PY" -m vllm.entrypoints.openai.api_server --model "$WEIGHTS" \
    --served-model-name "$MODEL" --host 127.0.0.1 --port "$PORT" --tensor-parallel-size 4 \
    --generation-config vllm --gpu-memory-utilization 0.88 --max-model-len 131072 --max-num-seqs 8 --enforce-eager \
    > "$JUDGE_JOB/server.log" 2>&1 &
JUDGE_PID=$!
trap 'kill "$JUDGE_PID" 2>/dev/null || true; wait "$JUDGE_PID" 2>/dev/null || true' EXIT
for ((attempt=0; attempt<360; attempt++)); do
    if curl --noproxy '*' -fsS --max-time 4 "$URL/models" > "$JUDGE_JOB/models.json" 2>/dev/null; then break; fi
    kill -0 "$JUDGE_PID"
    sleep 5
done
test -s "$JUDGE_JOB/models.json"
date -u +'%FT%TZ judge_ready'
REVISION=$(sha256sum "$WEIGHTS/config.json" | cut -d' ' -f1)
"$PY" -m ledger_grpo.ledgercredit ledger --selection "$STORE/round4_bcplus/selection" \
    --output "$PRIVATE/m2-$SLURM_JOB_ID" --m1 "$PRIVATE/m1-$2" --prepared "$PRIVATE/docs-$3" \
    --url "$URL" --model "$MODEL" --model-revision "config-sha256:$REVISION" \
    --conditions-version "bcplus-round4-$SLURM_JOB_ID-v2" \
    --condition-tokenizer "$WEIGHTS" --workers 8
