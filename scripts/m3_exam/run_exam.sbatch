#!/bin/bash
#SBATCH --job-name=m3-intent-exam
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

ROOT="${1:?private exam directory}"
COMMIT="${2:?exam code commit}"
REVIEW="${3:?frozen review input directory}"
OLD_TARGET="${4:?archived 187221 targets bound to the review manifest}"
REVIEW_COMMIT="${5:?published frozen review commit}"
BASE=/file_storage01/home/weiyu/lanyi
PY="$BASE/envs/successful_phase05_20261007/bin/python"
RUN="$ROOT/run-$SLURM_JOB_ID"
RPC="$BASE/i/docid/$SLURM_JOB_ID"
MODEL=gpt-oss-120b
CACHE="$RUN/runtime_cache"
test -s "$ROOT/source_manifest.json"
test -s "$OLD_TARGET"
test "$(( ${#RPC} + 37 ))" -le 107
mkdir -m 700 "$RUN"
mkdir -m 700 "$CACHE" "$RUN/tmp"
mkdir -p "$RPC"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
export HF_HOME="$CACHE/hf" XDG_CACHE_HOME="$CACHE/xdg" VLLM_CACHE_ROOT="$CACHE/vllm"
export VLLM_RPC_BASE_PATH="$RPC" TRITON_CACHE_DIR="$CACHE/triton" CUDA_CACHE_PATH="$CACHE/cuda"
export TIKTOKEN_CACHE_DIR="$CACHE/tiktoken" TMPDIR="$RUN/tmp" PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY OPENAI_API_KEY DEEPSEEK_API_KEY JUDGE_API_KEY
PORT=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
printf '{"job_id":%s,"code_commit":"%s","review_commit":"%s","endpoint":"http://127.0.0.1:%s/v1","model":"%s","reasoning_effort":"medium","temperature":0,"strict_json_schema":true,"workers":16,"max_num_seqs":16,"tensor_parallel_size":4,"timeout_seconds":900,"max_tokens":16000,"retry_limit":0}\n' \
  "$SLURM_JOB_ID" "$COMMIT" "$REVIEW_COMMIT" "$PORT" "$MODEL" > "$RUN/runtime.private.json"
printf '%s\n' "$COMMIT" > "$RUN/code_commit.txt"

date -u +'%FT%TZ batch_started'
"$PY" -m vllm.entrypoints.openai.api_server --model "$BASE/models/$MODEL" \
  --served-model-name "$MODEL" --host 127.0.0.1 --port "$PORT" --tensor-parallel-size 4 \
  --generation-config vllm --gpu-memory-utilization 0.88 --max-model-len 131072 --max-num-seqs 16 --enforce-eager \
  > "$RUN/model.log" 2>&1 &
SERVER=$!
trap 'kill "$SERVER" 2>/dev/null || true; wait "$SERVER" 2>/dev/null || true' EXIT
ready=0
for ((i=0; i<360; i++)); do
  if curl --noproxy '*' -fsS --max-time 4 "http://127.0.0.1:$PORT/v1/models" > /dev/null 2>&1; then
    ready=1
    break
  fi
  kill -0 "$SERVER"
  sleep 5
done
test "$ready" = 1
date -u +'%FT%TZ judge_ready'
"$PY" "$ROOT/run_exam.py" --review "$REVIEW" --manifest "$ROOT/source_manifest.json" --old-target "$OLD_TARGET" \
  --runtime "$RUN/runtime.private.json" --output "$RUN"
date -u +'%FT%TZ work_done'
