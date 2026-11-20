#!/bin/bash
#SBATCH --job-name=m2-v61-fix-replay
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=00:25:00
set -euo pipefail
umask 077
CODE="$1"
FULL="$2"
WORK="$3"
V4="$4"
shift 4
mkdir -p -m 700 "$WORK"
source "$FULL/local_env.sh" "$WORK"
export PYTHONPATH="$CODE:$FULL:$V4/src:$PYTHONPATH"
date -u +'%FT%TZ replay_start'
"$PY" "$CODE/run_fix.py" replay --out "$WORK" "$@"
date -u +'%FT%TZ replay_complete'
