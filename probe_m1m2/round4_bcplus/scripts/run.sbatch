#!/bin/bash
#SBATCH --job-name=bcplus-r4-4b
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
ROOT="${3:?run bulk directory}/run-$SLURM_JOB_ID"
BASE=/file_storage01/home/weiyu/lanyi
PROJECTS="$BASE/projects"
DELETION="$PROJECTS/ledger-grpo-pilot/runs/event-calibration-183352/services"
REFERENCE="$PROJECTS/deepsearch-world-pilot/probe_m1m2/round3/run-4B-191021"
LEDGER=/persist_data/home/weiyu/lanyi/projects/ledger-grpo-pilot/source/20261112-calibration-workflow-v2
PY="$BASE/envs/successful_phase05_20261007/bin/python"
export LEDGER_HF_BACKEND_SOURCE="$PROJECTS/browsecomp-qwen35-9b-grpo-smoke/runs/stability-tenstep-v4"
export LEDGER_PILOT_STORE="$BASE"
export LEDGER_ACTOR_MODEL="$BASE/models/Qwen3.5-4B--851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
export LEDGER_BC_TOOL_SCHEMA_REFERENCE="$PROJECTS/q4j/run-190197/rollout/EXECUTION_FREEZE.json"
export PYTHONPATH="$LEDGER/src:$LEDGER/scripts:$LEDGER_HF_BACKEND_SOURCE:$PROJECTS/browsecomp-qwen35-9b-grpo-smoke/python/fla-cuda-site"
export TMPDIR="$BASE/lcr4/t" VLLM_RPC_BASE_PATH="$BASE/lcr4/i"
export PYTHONPYCACHEPREFIX="$ROOT/cache/pycache"
export HF_HOME="$ROOT/cache/hf" HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export VLLM_CACHE_ROOT="$ROOT/cache/vllm" XDG_CACHE_HOME="$ROOT/cache/xdg"
export TRITON_CACHE_DIR="$ROOT/cache/triton" TORCHINDUCTOR_CACHE_DIR="$ROOT/cache/inductor"
export CUDA_CACHE_PATH="$ROOT/cache/cuda" TORCH_HOME="$ROOT/cache/torch" TIKTOKEN_CACHE_DIR="$ROOT/cache/tiktoken"
export PYTHONDONTWRITEBYTECODE=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=6
export VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True TZ=UTC
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY OPENAI_API_KEY DEEPSEEK_API_KEY JUDGE_API_KEY
mkdir -p "$TMPDIR" "$VLLM_RPC_BASE_PATH"
cd "$SOURCE"
"$PY" -u "$SOURCE/actor.py" "$ROOT" "$SELECTION/actor_questions.json" "$DELETION" "$REFERENCE"
date -u +'%FT%TZ actor_complete'
mkdir -p "$TIKTOKEN_CACHE_DIR"
PORT=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
URL="http://127.0.0.1:$PORT/v1"
MODEL=gpt-oss-120b
"$PY" -m vllm.entrypoints.openai.api_server --model "$BASE/models/$MODEL" \
    --served-model-name "$MODEL" --host 127.0.0.1 --port "$PORT" --tensor-parallel-size 4 \
    --generation-config vllm --gpu-memory-utilization 0.88 --max-model-len 131072 --max-num-seqs 4 --enforce-eager \
    > "$ROOT/JUDGE_SERVER.log" 2>&1 &
JUDGE_PID=$!
trap 'kill "$JUDGE_PID" 2>/dev/null || true; wait "$JUDGE_PID" 2>/dev/null || true' EXIT
for ((i=0; i<360; i++)); do
    if curl --noproxy '*' -fsS --max-time 4 "$URL/models" > "$ROOT/JUDGE_MODELS.json" 2>/dev/null; then break; fi
    kill -0 "$JUDGE_PID"
    sleep 5
done
test -s "$ROOT/JUDGE_MODELS.json"
date -u +'%FT%TZ judge_ready'
"$PY" -u "$SOURCE/score.py" "$ROOT" "$SELECTION/evaluation_private.json" "$URL" "$MODEL"
date -u +'%FT%TZ pilot_complete'
