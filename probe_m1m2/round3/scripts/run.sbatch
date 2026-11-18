#!/bin/bash
#SBATCH --job-name=dsw-paired100
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
SOURCE="$1"
DEDUP="$2"
export LEDGER_ACTOR_SIZE="$3"
[[ "$LEDGER_ACTOR_SIZE" == 4B || "$LEDGER_ACTOR_SIZE" == 9B ]]
BASE=/file_storage01/home/weiyu/lanyi
STORE="$BASE/projects/deepsearch-world-pilot"
ROOT="$STORE/probe_m1m2/round3/run-$LEDGER_ACTOR_SIZE-$SLURM_JOB_ID"
ENV="$BASE/envs/successful_phase05_20261007"
RETRIEVAL="$BASE/envs/ricepo-retrieval-overlay-v1"
LEDGER=/persist_data/home/weiyu/lanyi/projects/ledger-grpo-pilot/source/20261112-calibration-workflow-v2
export LEDGER_HF_BACKEND_SOURCE="$BASE/projects/browsecomp-qwen35-9b-grpo-smoke/runs/stability-tenstep-v4"
export LEDGER_PILOT_STORE="$STORE"
if [[ "$LEDGER_ACTOR_SIZE" == 4B ]]; then
    export LEDGER_ACTOR_MODEL="$BASE/models/Qwen3.5-4B--851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
    REFERENCE="$STORE/pilot-4b-190085"
else
    export LEDGER_ACTOR_MODEL="$BASE/models/Qwen3.5-9B"
    REFERENCE="$STORE/pilot-184534"
fi
export PYTHONPATH="$LEDGER/src:$LEDGER/scripts:$LEDGER_HF_BACKEND_SOURCE:$BASE/projects/browsecomp-qwen35-9b-grpo-smoke/python/fla-cuda-site"
export JAVA_HOME="$BASE/envs/ricepo-temurin21-21.0.12.1_1"
export PATH="$JAVA_HOME/bin:$PATH"
export PYTHONPYCACHEPREFIX="$STORE/cache/pycache" TMPDIR="$STORE/t"
export VLLM_RPC_BASE_PATH="$STORE/i"
export HF_HOME="$STORE/cache/huggingface" HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export VLLM_CACHE_ROOT="$STORE/cache/vllm" XDG_CACHE_HOME="$STORE/cache/xdg"
export TRITON_CACHE_DIR="$STORE/cache/triton" TORCHINDUCTOR_CACHE_DIR="$STORE/cache/inductor"
export CUDA_CACHE_PATH="$STORE/cache/cuda" TORCH_HOME="$STORE/cache/torch"
export TIKTOKEN_CACHE_DIR="$STORE/cache/tiktoken" TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=6
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY OPENAI_API_KEY DEEPSEEK_API_KEY JUDGE_API_KEY
mkdir -p "$TMPDIR" "$VLLM_RPC_BASE_PATH" "$TIKTOKEN_CACHE_DIR"
LOGS="$STORE/logs"
READY="$LOGS/wiki-$SLURM_JOB_ID.json"
WIKI_PID=
JUDGE_PID=
cleanup() {
    for pid in "$WIKI_PID" "$JUDGE_PID"; do
        if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi
    done
}
trap cleanup EXIT
date -u +'%FT%TZ batch_start'
CUDA_VISIBLE_DEVICES= PYTHONPATH="$STORE/retrieval/pyserini-1.5.0" "$RETRIEVAL/bin/python" -u "$SOURCE/wiki.py" "$STORE/environment" "$READY" > "$LOGS/wiki-$SLURM_JOB_ID.log" 2>&1 &
WIKI_PID=$!
for ((i=0; i<120; i++)); do
    [[ -s "$READY" ]] && break
    kill -0 "$WIKI_PID"
    sleep 2
done
test -s "$READY"
date -u +'%FT%TZ local_wiki_ready'
"$ENV/bin/python" -u "$SOURCE/actor.py" "$ROOT" "$DEDUP/PILOT_ACTOR.json" "$READY" "$REFERENCE"
date -u +'%FT%TZ actor_complete'
PORT=$("$ENV/bin/python" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
URL="http://127.0.0.1:$PORT/v1"
MODEL=gpt-oss-120b
"$ENV/bin/python" -m vllm.entrypoints.openai.api_server --model "$BASE/models/$MODEL" \
    --served-model-name "$MODEL" --host 127.0.0.1 --port "$PORT" --tensor-parallel-size 4 \
    --generation-config vllm --gpu-memory-utilization 0.88 --max-model-len 131072 --max-num-seqs 4 --enforce-eager \
    > "$ROOT/JUDGE_SERVER.log" 2>&1 &
JUDGE_PID=$!
for ((i=0; i<360; i++)); do
    if curl --noproxy '*' -fsS --max-time 4 "$URL/models" > "$ROOT/JUDGE_MODELS.json" 2>/dev/null; then break; fi
    kill -0 "$JUDGE_PID"
    sleep 5
done
test -s "$ROOT/JUDGE_MODELS.json"
date -u +'%FT%TZ judge_ready'
"$ENV/bin/python" -u "$SOURCE/score.py" "$ROOT" "$DEDUP/PILOT_PRIVATE.json" "$URL" "$MODEL"
date -u +'%FT%TZ pilot_complete'
