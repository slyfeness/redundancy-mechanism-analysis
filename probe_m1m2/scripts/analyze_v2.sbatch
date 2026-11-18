#!/bin/bash
#SBATCH --job-name=probe-m1m2-analyze
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=00:30:00
set -euo pipefail
umask 077
export PROBE_OUT=/file_storage01/home/weiyu/lanyi/projects/deepsearch-world-pilot/probe_m1m2
export PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export HF_HOME="$PROBE_OUT/cache" XDG_CACHE_HOME="$PROBE_OUT/cache" TMPDIR="$PROBE_OUT/tmp"
mkdir -p "$TMPDIR"
printf '%s\n' "$0 $*" >> "$PROBE_OUT/commands.log"
/file_storage01/home/weiyu/lanyi/envs/successful_phase05_20261007/bin/python "$1/analyze_v2.py"
