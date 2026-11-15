#!/bin/bash
#SBATCH --job-name=docid-snippet-pilot
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

CONTROL="${1:?private trial directory}"
COMMIT="${2:?code commit}"
CPU_JOB="${3:?CPU receipt job ID}"
BASE=/file_storage01/home/weiyu/lanyi
PY="$BASE/envs/successful_phase05_20261007/bin/python"
RUN="$CONTROL/run-$SLURM_JOB_ID"
RPC="$BASE/i/docid/$SLURM_JOB_ID"
MODEL=gpt-oss-120b
CACHE="$RUN/runtime_cache"
test -s "$CONTROL/prepared/snippet_check.json"
test -s "$CONTROL/prepared/inputs.private.json"
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
printf '{"job_id":%s,"cpu_job_id":%s,"code_commit":"%s","endpoint":"http://127.0.0.1:%s/v1","model":"%s","reasoning_effort":"medium","temperature":0,"strict_json_schema":1,"workers":8,"timeout_seconds":900,"max_tokens":16000,"seed":20261117,"source_visibility_job_id":187221,"source_docid_job_id":187299,"retry_limit":0}\n' \
    "$SLURM_JOB_ID" "$CPU_JOB" "$COMMIT" "$PORT" "$MODEL" > "$RUN/runtime.private.json"
date -u +'%FT%TZ batch_started'
"$PY" -m vllm.entrypoints.openai.api_server --model "$BASE/models/$MODEL" \
    --served-model-name "$MODEL" --host 127.0.0.1 --port "$PORT" --tensor-parallel-size 4 \
    --generation-config vllm --gpu-memory-utilization 0.88 --max-model-len 131072 --max-num-seqs 16 --enforce-eager \
    > "$RUN/model.log" 2>&1 &
SERVER=$!
trap 'kill "$SERVER" 2>/dev/null || true; wait "$SERVER" 2>/dev/null || true' EXIT
ready=0
for ((a=0; a<360; a++)); do
    if curl --noproxy '*' -fsS --max-time 4 "http://127.0.0.1:$PORT/v1/models" > /dev/null 2>&1; then
        ready=1
        break
    fi
    kill -0 "$SERVER"
    sleep 5
done
test "$ready" = 1
date -u +'%FT%TZ judge_ready'
"$PY" "$CONTROL/snippet_pilot.py" --prepared "$CONTROL/prepared" --output "$RUN" --config "$RUN/runtime.private.json"
date -u +'%FT%TZ pilot_complete'
