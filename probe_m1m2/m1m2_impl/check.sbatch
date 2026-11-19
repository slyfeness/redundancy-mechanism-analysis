#!/bin/bash
#SBATCH --job-name=ledger-m1m2-cpu
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=04:00:00
set -euo pipefail
umask 077
BASE=/file_storage01/home/weiyu/lanyi
STORE="$BASE/projects/ledger-grpo-pilot/probe_m1m2"
PRIVATE="$STORE/m1m2_impl"
export PYTHONPATH="$1/src"
export PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export HF_HOME="$PRIVATE/cache" XDG_CACHE_HOME="$PRIVATE/cache"
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
PY="$BASE/envs/successful_phase05_20261007/bin/python"
ROUND4="$STORE/round4_bcplus"
case "$2" in
    verify)
        "$PY" -m unittest discover -s "$1/tests" -p test_ledgercredit.py -v
        ;;
    m1)
        "$PY" -m ledger_grpo.ledgercredit stages --selection "$ROUND4/selection" \
            --run "$ROUND4/run-191882" --output "$PRIVATE/m1-$SLURM_JOB_ID" \
            --outcome-retry "$ROUND4/retry-192051/verdicts" \
            --tokenizer "$BASE/models/Qwen3.5-4B--851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
        ;;
    docs)
        "$PY" -m ledger_grpo.ledgercredit evidence-docs --selection "$ROUND4/selection" \
            --corpus "$BASE/projects/新实验/assets/browsecomp-plus/corpus" \
            --output "$PRIVATE/docs-$SLURM_JOB_ID"
        ;;
    replay)
        REVISION=$(sha256sum "$BASE/models/gpt-oss-120b/config.json" | cut -d' ' -f1)
        "$PY" -m ledger_grpo.ledgercredit ledger --selection "$ROUND4/selection" \
            --m1 "$PRIVATE/m1-$3" --prepared "$PRIVATE/docs-$4" --reuse-results "$PRIVATE/m2-$5" \
            --model-revision "config-sha256:$REVISION" --conditions-version "bcplus-round4-$5-$6" \
            --output "$PRIVATE/m2-$SLURM_JOB_ID"
        ;;
    *)
        exit 2
        ;;
esac
