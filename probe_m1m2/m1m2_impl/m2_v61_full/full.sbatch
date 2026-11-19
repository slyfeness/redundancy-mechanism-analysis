#!/bin/bash
#SBATCH --job-name=m2-v61-full
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
PHASE="$1"
CODE="$2"
ROOT="$3"
PREP="$4"
EMBEDDING="$5"
V4="$6"
V6="$7"
V61="$8"
WORK="${9:-$ROOT/m2-v61-full-$SLURM_JOB_ID}"
mkdir -p "$WORK"
source "$CODE/local_env.sh" "$WORK"
export PYTHONPATH="$V4/src:$PYTHONPATH"
WEIGHTS="$BASE/models/gpt-oss-120b"
test "$(sha256sum "$WEIGHTS/config.json" | cut -d' ' -f1)" = 933aeb666a3fd851133ddd7686414f369bc564c4185fb5704416550879f10566
ARGS=(--root "$ROOT" --prep "$PREP" --embedding "$EMBEDDING" --v4 "$V4" --v6 "$V6" --v61 "$V61"
      --out "$WORK" --model "$WEIGHTS")
date -u +'%FT%TZ full_batch_start'
if test "$PHASE" = settle; then
    "$PY" "$CODE/run_full.py" plan "${ARGS[@]}"
    if test "$(cat "$WORK/gold_queries.json")" != '[]'; then
        mkdir -m 700 "$WORK/gold_embed"
        "$PY" -m torch.distributed.run --standalone --nproc-per-node=4 "$CODE/embed.py" gold \
            --base "$BASE" --prep "$PREP" --out "$WORK/gold_embed" --queries "$WORK/gold_queries.json"
    fi
fi
PORT=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
URL="http://127.0.0.1:$PORT/v1"
"$PY" -m vllm.entrypoints.openai.api_server --model "$WEIGHTS" \
    --served-model-name gpt-oss-120b --host 127.0.0.1 --port "$PORT" --tensor-parallel-size 4 \
    --generation-config vllm --gpu-memory-utilization 0.88 --max-model-len 131072 --max-num-seqs 24 \
    --max-num-batched-tokens 16384 --enforce-eager >"$WORK/server-$PHASE-$SLURM_JOB_ID.log" 2>&1 &
JUDGE_PID=$!
trap 'kill "$JUDGE_PID" 2>/dev/null || true; wait "$JUDGE_PID" 2>/dev/null || true' EXIT
MODELS="$WORK/models-$PHASE-$SLURM_JOB_ID.json"
for ((attempt=0; attempt<360; attempt++)); do
    if curl --noproxy '*' -fsS --max-time 4 "$URL/models" >"$MODELS" 2>/dev/null; then break; fi
    kill -0 "$JUDGE_PID"
    sleep 5
done
test -s "$MODELS"
date -u +'%FT%TZ judge_ready'
"$PY" "$CODE/run_full.py" "$PHASE" "${ARGS[@]}" --url "$URL"
date -u +'%FT%TZ full_phase_complete'
