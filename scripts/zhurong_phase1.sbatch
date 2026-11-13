#!/bin/bash
#SBATCH --job-name=redundancy-phase1
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
SOURCE="${1:?source path}"
INVENTORY="${2:?inventory path}"
COMMIT="${3:?code commit}"
MODE="${4:-pilot}"
BASE=/file_storage01/home/weiyu/lanyi
STORE="$BASE/projects/redundancy-judge-phase1"
RUN="$STORE/run-$SLURM_JOB_ID"
PY="$BASE/envs/successful_phase05_20261007/bin/python"
mkdir -p "$RUN" "$STORE/cache" "$STORE/tmp/$SLURM_JOB_ID" "$STORE/i/$SLURM_JOB_ID"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
export HF_HOME="$STORE/cache/hf" XDG_CACHE_HOME="$STORE/cache/xdg"
export VLLM_CACHE_ROOT="$STORE/cache/vllm" VLLM_RPC_BASE_PATH="$STORE/i/$SLURM_JOB_ID"
export TRITON_CACHE_DIR="$STORE/cache/triton" CUDA_CACHE_PATH="$STORE/cache/cuda"
export TIKTOKEN_CACHE_DIR="$STORE/cache/tiktoken" TMPDIR="$STORE/tmp/$SLURM_JOB_ID"
export PYTHONPYCACHEPREFIX="$STORE/cache/pycache" PYTHONPATH="$SOURCE/src"
export OMP_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY OPENAI_API_KEY DEEPSEEK_API_KEY JUDGE_API_KEY
PORT=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
MODEL=gpt-oss-120b
MODEL_DIR="$BASE/models/$MODEL"
(
    cd "$MODEL_DIR"
    sha256sum config.json generation_config.json tokenizer.json chat_template.jinja model.safetensors.index.json
    stat --format='%n %s %Y' model-*.safetensors
    for shard in model-*.safetensors; do
        metadata=".cache/huggingface/download/$shard.metadata"
        if [[ -f "$metadata" ]]; then
            printf '%s upstream metadata ' "$shard"
            head -2 "$metadata" | paste -sd ' ' -
        fi
    done
) > "$RUN/judge_model_files.txt"
JUDGE_ID=$(sha256sum "$RUN/judge_model_files.txt" | cut -d ' ' -f 1)
cat > "$RUN/config.json" <<EOF
{"mode":"real","input_index":"$INVENTORY/input_index.jsonl","output_dir":"$RUN","run_dir":"$RUN/real","prompt_dir":"$SOURCE/prompts","tokenizer":"$BASE/models/Qwen3.5-9B/tokenizer.json","tokenizer_revision":"c202236235762e1c871ad0ccb60c8ee5ba337b9a","code_commit":"$COMMIT","judge":{"url":"http://127.0.0.1:$PORT/v1","model":"$MODEL","version":"$MODEL:$JUDGE_ID","timeout":180,"max_tokens":4096},"workers":12,"threshold":0.8,"pilot_seed":20261113,"cost_weighted":true,"reward":{"w_g":0.1,"prices":{"R1":0.05,"R2b":0.10,"R2a":0.0},"trajectory_price_cap":0.5,"group_size":4}}
EOF
date -u +'%FT%TZ batch_start'
if [[ "$MODE" == pilot ]]; then
    run=(--split dev --limit-questions 5)
elif [[ "$MODE" == all ]]; then
    run=(--split all --resume)
else
    exit 2
fi
if [[ "$MODE" == all && -n "${5:-}" ]]; then
    mkdir -p "$RUN/real"
    ln -s "$5/real/model_cache" "$RUN/real/model_cache"
fi
"$PY" -m vllm.entrypoints.openai.api_server --model "$BASE/models/$MODEL" \
    --served-model-name "$MODEL" --host 127.0.0.1 --port "$PORT" --tensor-parallel-size 4 \
    --generation-config vllm --gpu-memory-utilization 0.88 --max-model-len 131072 --max-num-seqs 16 --enforce-eager \
    > "$RUN/model.log" 2>&1 &
SERVER=$!
trap 'kill "$SERVER" 2>/dev/null || true; wait "$SERVER" 2>/dev/null || true' EXIT
for ((a=0; a<360; a++)); do
    if curl --noproxy '*' -fsS --max-time 4 "http://127.0.0.1:$PORT/v1/models" > "$RUN/models.json" 2>/dev/null; then break; fi
    kill -0 "$SERVER"
    sleep 5
done
test -s "$RUN/models.json"
date -u +'%FT%TZ judge_ready'
"$PY" -m redundancy_judge.cli inspect --config "$RUN/config.json"
"$PY" -m redundancy_judge.cli annotate --config "$RUN/config.json" "${run[@]}"
date -u +'%FT%TZ annotation_complete'
if [[ "$MODE" == all ]]; then
    for command in export-review audit reward-preview; do
        "$PY" -m redundancy_judge.cli "$command" --config "$RUN/config.json"
    done
fi
date -u +'%FT%TZ workflow_complete'
