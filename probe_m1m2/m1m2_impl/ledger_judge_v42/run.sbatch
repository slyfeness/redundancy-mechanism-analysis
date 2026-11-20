#!/bin/bash
#SBATCH --job-name=ledger-judge-v42
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
CODE="$1"
FULL="$2"
FLAGS="$3"
ROOT="$4"
PREP="$5"
FIXED="$6"
PREVIOUS="$7"
V4="$8"
V2="$9"
ORIGINAL="${10}"
V4CODE="${11}"
PRIOR_V41="${12}"
V41CODE="${13}"
WORK="${14:-$ROOT/ledger-judge-v42-$SLURM_JOB_ID}"
mkdir -p -m 700 "$WORK"
source "$FULL/local_env.sh" "$WORK"
export PYTHONPATH="$CODE:$V41CODE:$V4CODE:$V2:$FULL:$FLAGS:$V4/src:$PYTHONPATH"
WEIGHTS="$BASE/models/gpt-oss-120b"
test "$(sha256sum "$WEIGHTS/config.json" | cut -d' ' -f1)" = 933aeb666a3fd851133ddd7686414f369bc564c4185fb5704416550879f10566
ARGS=(--root "$ROOT" --prep "$PREP" --fixed "$FIXED" --previous "$PREVIOUS"
      --model "$WEIGHTS" --v4 "$V4" --out "$WORK" --original "$ORIGINAL" --previous-v41 "$PRIOR_V41")
date -u +'%FT%TZ batch_start'
PORT=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
URL="http://127.0.0.1:$PORT/v1"
"$PY" -m vllm.entrypoints.openai.api_server --model "$WEIGHTS" \
    --served-model-name gpt-oss-120b --host 127.0.0.1 --port "$PORT" --tensor-parallel-size 4 \
    --generation-config vllm --gpu-memory-utilization 0.88 --max-model-len 131072 --max-num-seqs 32 \
    --max-num-batched-tokens 16384 --enforce-eager >"$WORK/server-$SLURM_JOB_ID.log" 2>&1 &
JUDGE_PID=$!
trap 'kill "$JUDGE_PID" 2>/dev/null || true; wait "$JUDGE_PID" 2>/dev/null || true' EXIT
for ((attempt=0; attempt<360; attempt++)); do
    if curl --noproxy '*' -fsS --max-time 4 "$URL/models" >"$WORK/models-$SLURM_JOB_ID.json" 2>/dev/null; then break; fi
    kill -0 "$JUDGE_PID"
    sleep 5
done
test -s "$WORK/models-$SLURM_JOB_ID.json"
date -u +'%FT%TZ judge_ready'
"$PY" "$CODE/probe_v42.py" "${ARGS[@]}" --url "$URL"
date -u +'%FT%TZ probe_complete'
