#!/bin/bash
#SBATCH --job-name=constraint-trial
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=24
#SBATCH --mem=384G
#SBATCH --time=02:00:00
# usage: sbatch constraint_trial.sbatch <trial_dir> <input_index.jsonl> [question_ids.txt]
set -euo pipefail
umask 077
TRIAL="${1:?trial dir containing constraint_trial.py and constraint_prompt.md}"
INDEX="${2:?private input_index.jsonl}"
IDS="${3:-}"
BASE=/file_storage01/home/weiyu/lanyi
STORE="$BASE/projects/redundancy-judge-phase1"
RUN="$STORE/constraint-trial-$SLURM_JOB_ID"
PY="$BASE/envs/successful_phase05_20261007/bin/python"
RPC="$BASE/i/ctrial/$SLURM_JOB_ID"
CACHE="$STORE/constraint-trial-cache/$SLURM_JOB_ID"
printf "%s batch_started\n" "$(date -u +%FT%TZ)"
mkdir -p "$CACHE" "$STORE/tmp/$SLURM_JOB_ID" "$RPC"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
export HF_HOME="$CACHE/hf" XDG_CACHE_HOME="$CACHE/xdg"
export VLLM_CACHE_ROOT="$CACHE/vllm" VLLM_RPC_BASE_PATH="$RPC"
export TRITON_CACHE_DIR="$CACHE/triton" CUDA_CACHE_PATH="$CACHE/cuda"
export TIKTOKEN_CACHE_DIR="$CACHE/tiktoken" TMPDIR="$STORE/tmp/$SLURM_JOB_ID"
export OMP_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY OPENAI_API_KEY DEEPSEEK_API_KEY JUDGE_API_KEY
PORT=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
MODEL=gpt-oss-120b
LOGDIR="$STORE/tmp/$SLURM_JOB_ID"
"$PY" -m vllm.entrypoints.openai.api_server --model "$BASE/models/$MODEL" \
    --served-model-name "$MODEL" --host 127.0.0.1 --port "$PORT" --tensor-parallel-size 4 \
    --generation-config vllm --gpu-memory-utilization 0.88 --max-model-len 131072 --max-num-seqs 16 --enforce-eager \
    > "$LOGDIR/model.log" 2>&1 &
SERVER=$!
date -u +'%FT%TZ judge_starting'
trap 'kill "$SERVER" 2>/dev/null || true; wait "$SERVER" 2>/dev/null || true' EXIT
ready=0
for ((a=0; a<360; a++)); do
    if curl --noproxy '*' -fsS --max-time 4 "http://127.0.0.1:$PORT/v1/models" > /dev/null 2>&1; then ready=1; break; fi
    kill -0 "$SERVER"
    sleep 5
done
if [[ "$ready" != 1 ]]; then echo "Local model never became ready" >&2; exit 1; fi
date -u +'%FT%TZ judge_ready'
extra=()
if [[ -n "$IDS" ]]; then extra=(--question-ids "$IDS"); fi
"$PY" "$TRIAL/constraint_trial.py" --input-index "$INDEX" --url "http://127.0.0.1:$PORT/v1" \
    --model "$MODEL" --output-dir "$RUN" "${extra[@]}"
cp "$LOGDIR/model.log" "$RUN/model.log"
date -u +'%FT%TZ trial_complete'
echo "outputs in $RUN"
