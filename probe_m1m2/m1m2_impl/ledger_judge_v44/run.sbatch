#!/bin/bash
#SBATCH --job-name=ledger-judge-v44
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
CONTROL="$2"
ROOT="$3"
WORK="${4:-$ROOT/ledger-judge-v44-$SLURM_JOB_ID}"
MODE="${5:-live}"
FULL="$CONTROL/m2-v61-full.7U7YVl/m2_v61_full"
mkdir -p -m 700 "$WORK"
source "$FULL/local_env.sh" "$WORK"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$CODE:$CONTROL/ledger-judge-v43.IA7Kxv:$CONTROL/ledger-judge-v42.uSU7aZ:$CONTROL/ledger-judge-v41.HBCkIG:$CONTROL/ledger-judge-v4.VwO7CV:$CONTROL/ledger-judge-v2.bVAXnm:$FULL:$CONTROL/fpremise-probe.nj7gKC:$CONTROL/m1m2_impl-v8/src:$PYTHONPATH"
ARGS=(--root "$ROOT" --prep "$ROOT/m2-v61-full-prep-192982" --fixed "$ROOT/m2-v61-fix-192990"
      --previous "$ROOT/ledger-judge-probe-193495" --v42 "$ROOT/ledger-judge-v42-193729/ledger_judge_v42"
      --v43 "$ROOT/ledger-judge-v43-193760" --country-catalog /usr/share/iso-codes/json/iso_3166-1.json --out "$WORK")
date -u +'%FT%TZ batch_start'
case "$MODE" in
    preflight)
        "$PY" -m unittest discover -s "$CODE" -p test_v44.py
        "$PY" "$CODE/probe_v44.py" "${ARGS[@]}" --preflight
        exit
        ;;
    audit)
        "$PY" "$CODE/audit_v44.py" "$WORK/release-index.json" "${ARGS[@]}"
        exit
        ;;
    live) ;;
    *) exit 2 ;;
esac
WEIGHTS="$BASE/models/gpt-oss-120b"
test "$(sha256sum "$WEIGHTS/config.json" | cut -d' ' -f1)" = 933aeb666a3fd851133ddd7686414f369bc564c4185fb5704416550879f10566
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
"$PY" "$CODE/probe_v44.py" "${ARGS[@]}" --url "$URL"
date -u +'%FT%TZ probe_complete'
