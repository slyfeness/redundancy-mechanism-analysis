#!/bin/bash
#SBATCH --job-name=ledger-local-event-judge
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
date -u +"batch_start %FT%TZ"
SOURCE=$(realpath -e "${1:?supply the local calibration source}")
CONTINUATION="${2:?supply the audited continuation job ID}"
[[ $CONTINUATION =~ ^[0-9]+$ ]]
MODEL="${3:-gpt-oss-120b}"
case "$MODEL" in
  gpt-oss-120b) MODEL_ARGS=(--max-model-len 131072) ;;
  Qwen3-32B) MODEL_ARGS=(--max-model-len 40960 --default-chat-template-kwargs '{"enable_thinking":false}') ;;
  *) exit 2 ;;
esac
BASE=/file_storage01/home/weiyu/lanyi
STORE="$BASE/projects/ledger-grpo-pilot"
PYTHON="$BASE/envs/successful_phase05_20261007/bin/python"
RUN="$STORE/runs/pilot-182516"
PLAN="$STORE/reports/event-calibration-plan-182516-182710"
AUDIT="$STORE/reports/event-deletion-prefixes-182516-182698.json"
ROOT="$STORE/reports/local-event-calibration-$SLURM_JOB_ID"
test -s "$STORE/reports/live-event-calibration-$CONTINUATION.json"
mkdir "$ROOT"
cd "$ROOT"
export PYTHONPATH="$SOURCE/src:$SOURCE/scripts"
export PYTHONPYCACHEPREFIX="$STORE/runtime-pycache" TMPDIR="$STORE/tmp"
export VLLM_RPC_BASE_PATH="$STORE/i/$SLURM_JOB_ID"
export HF_HOME="$STORE/cache/huggingface" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export VLLM_CACHE_ROOT="$STORE/cache/vllm" XDG_CACHE_HOME="$STORE/cache/xdg"
export TRITON_CACHE_DIR="$STORE/cache/triton" TORCHINDUCTOR_CACHE_DIR="$STORE/cache/inductor"
export CUDA_CACHE_PATH="$STORE/cache/cuda" TORCH_HOME="$STORE/cache/torch"
export TIKTOKEN_CACHE_DIR="$STORE/cache/tiktoken"
export OMP_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false
mkdir -p "$VLLM_RPC_BASE_PATH" "$TIKTOKEN_CACHE_DIR"
PORT=$("$PYTHON" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
URL="http://127.0.0.1:$PORT/v1"
printf '%s\n' "$MODEL" > MODEL.txt
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader > HARDWARE.txt
"$PYTHON" -m vllm.entrypoints.openai.api_server --model "$BASE/models/$MODEL" \
  --served-model-name "$MODEL" --host 127.0.0.1 --port "$PORT" --tensor-parallel-size 4 \
  --generation-config vllm --gpu-memory-utilization 0.88 --max-num-seqs 4 --enforce-eager \
  "${MODEL_ARGS[@]}" > SERVER.log 2>&1 &
SERVER=$!
trap 'kill "$SERVER" 2>/dev/null || true; wait "$SERVER" 2>/dev/null || true' EXIT
for ((attempt=0; attempt<360; attempt++)); do
  if curl --noproxy '*' -fsS --max-time 4 "$URL/models" > MODELS.json 2>/dev/null; then
    break
  fi
  kill -0 "$SERVER"
  sleep 5
done
test -s MODELS.json
"$PYTHON" - "$URL" "$MODEL" <<'PY'
from ledger_grpo.client import LocalJudge
import sys
judge = LocalJudge(sys.argv[1], sys.argv[2], timeout=60, max_tokens=4096)
if judge._request('Return exactly {"ready":true}.', {}) != {'ready': True}:
    raise RuntimeError('local structured output probe failed')
PY
date -u +"judge_ready %FT%TZ"
"$PYTHON" -u "$SOURCE/scripts/diagnose_semantic_events.py" --run "$RUN" --plan "$PLAN/PLAN.json" \
  --audit "$AUDIT" --coordinates "$STORE/reports/tool-coordinates-182516-served.json" \
  --judge-base-url "$URL" --judge-model "$MODEL" --output SEMANTIC_PREDICTIONS.json
"$PYTHON" -u "$SOURCE/scripts/frozen_event_calibration.py" --plan "$PLAN/PLAN.json" --packet "$PLAN/BLIND_REVIEW.json" \
  --audit "$AUDIT" --native-batch "$RUN/scored/NATIVE_BATCH.json" --private-plan "$STORE/plans/pilot-182406/PRIVATE_PLAN.json" \
  --execution "$STORE/runs/event-calibration-182887/branches" \
  --execution "$STORE/runs/event-calibration-$CONTINUATION/branches" \
  --predictions SEMANTIC_PREDICTIONS.json --local-judge-url "$URL" --local-judge-model "$MODEL" --output calibration
date -u +"calibration_ready %FT%TZ"
