#!/bin/bash
#SBATCH --job-name=ledger-m2-v4
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
ROOT="$2"
WORK="$3"
MODE="$4"
PREVIOUS="$5"
BASE=/file_storage01/home/weiyu/lanyi
PY="$BASE/envs/successful_phase05_20261007/bin/python"
WEIGHTS="$BASE/models/gpt-oss-120b"
test "$(sha256sum "$WEIGHTS/config.json" | cut -d' ' -f1)" = 933aeb666a3fd851133ddd7686414f369bc564c4185fb5704416550879f10566
export PYTHONPATH="$CONTROL/src" PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
SERVICE="$WORK/service-$SLURM_JOB_ID"
mkdir "$SERVICE"
export HF_HOME="$SERVICE/cache/hf" XDG_CACHE_HOME="$SERVICE/cache/xdg"
export VLLM_CACHE_ROOT="$SERVICE/cache/vllm" TIKTOKEN_CACHE_DIR="$SERVICE/cache/tiktoken"
export TRITON_CACHE_DIR="$SERVICE/cache/triton" TORCHINDUCTOR_CACHE_DIR="$SERVICE/cache/inductor"
export CUDA_CACHE_PATH="$SERVICE/cache/cuda" TORCH_HOME="$SERVICE/cache/torch"
export TMPDIR="$BASE/lm4-t-$SLURM_JOB_ID" VLLM_RPC_BASE_PATH="$BASE/lm4-i-$SLURM_JOB_ID"
export VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=6
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY OPENAI_API_KEY DEEPSEEK_API_KEY JUDGE_API_KEY
mkdir -p "$TMPDIR" "$VLLM_RPC_BASE_PATH" "$TIKTOKEN_CACHE_DIR"
if test -d "$ROOT/cache/tiktoken"; then cp -a "$ROOT/cache/tiktoken/." "$TIKTOKEN_CACHE_DIR/"; fi
date -u +'%FT%TZ batch_start'
PORT=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
URL="http://127.0.0.1:$PORT/v1"
"$PY" -m vllm.entrypoints.openai.api_server --model "$WEIGHTS" \
  --served-model-name gpt-oss-120b --host 127.0.0.1 --port "$PORT" --tensor-parallel-size 4 \
  --generation-config vllm --gpu-memory-utilization 0.88 --max-model-len 131072 --max-num-seqs 8 --enforce-eager \
  >"$SERVICE/server.log" 2>&1 &
JUDGE_PID=$!
trap 'kill "$JUDGE_PID" 2>/dev/null || true; wait "$JUDGE_PID" 2>/dev/null || true' EXIT
for ((attempt=0; attempt<360; attempt++)); do
    if curl --noproxy '*' -fsS --max-time 4 "$URL/models" >"$SERVICE/models.json" 2>/dev/null; then break; fi
    kill -0 "$JUDGE_PID"
    sleep 5
done
test -s "$SERVICE/models.json"
date -u +'%FT%TZ judge_ready'
case "$MODE" in
    pilot)
        "$PY" "$CONTROL/judge_v4/pilot.py" pilot --root "$ROOT" --previous "$PREVIOUS" \
          --inputs "$WORK/inputs" --out "$WORK/pilot" --url "$URL"
        ;;
    full)
        "$PY" "$CONTROL/judge_v4/pilot.py" full --root "$ROOT" --previous "$PREVIOUS" \
          --pilot "$WORK/pilot" --out "$WORK/m2-v4-$SLURM_JOB_ID" --url "$URL"
        ;;
    *) exit 2 ;;
esac
date -u +'%FT%TZ complete'
