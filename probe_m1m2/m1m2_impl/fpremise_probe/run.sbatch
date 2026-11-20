#!/bin/bash
#SBATCH --job-name=fpremise-probe
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
ROOT="$3"
PREP="$4"
FIXED="$5"
V4="$6"
WORK="$ROOT/fpremise-probe-$SLURM_JOB_ID"
mkdir -m 700 "$WORK"
source "$FULL/local_env.sh" "$WORK"
export PYTHONPATH="$CODE:$FULL:$V4/src:$PYTHONPATH"
WEIGHTS="$BASE/models/gpt-oss-120b"
test "$(sha256sum "$WEIGHTS/config.json" | cut -d' ' -f1)" = 933aeb666a3fd851133ddd7686414f369bc564c4185fb5704416550879f10566
ARGS=(--root "$ROOT" --prep "$PREP" --fixed "$FIXED" --v4 "$V4" --out "$WORK")
date -u +'%FT%TZ batch_start'
"$PY" "$CODE/probe.py" prepare "${ARGS[@]}"
PORT=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
URL="http://127.0.0.1:$PORT/v1"
"$PY" -m vllm.entrypoints.openai.api_server --model "$WEIGHTS" \
    --served-model-name gpt-oss-120b --host 127.0.0.1 --port "$PORT" --tensor-parallel-size 4 \
    --generation-config vllm --gpu-memory-utilization 0.88 --max-model-len 131072 --max-num-seqs 8 \
    --enforce-eager >"$WORK/server.log" 2>&1 &
JUDGE_PID=$!
trap 'kill "$JUDGE_PID" 2>/dev/null || true; wait "$JUDGE_PID" 2>/dev/null || true' EXIT
for ((attempt=0; attempt<360; attempt++)); do
    if curl --noproxy '*' -fsS --max-time 4 "$URL/models" >"$WORK/models.json" 2>/dev/null; then break; fi
    kill -0 "$JUDGE_PID"
    sleep 5
done
test -s "$WORK/models.json"
date -u +'%FT%TZ judge_ready'
"$PY" "$CODE/probe.py" judge "${ARGS[@]}" --url "$URL"
date -u +'%FT%TZ probe_complete'
