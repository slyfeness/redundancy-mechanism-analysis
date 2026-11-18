#!/bin/bash
#SBATCH --job-name=probe-native-mask
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=00:15:00
set -euo pipefail
umask 077
export PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4
BASE=/file_storage01/home/weiyu/lanyi/projects/deepsearch-world-pilot/probe_m1m2
export HF_HOME="$BASE/cache" XDG_CACHE_HOME="$BASE/cache" TMPDIR="$BASE/tmp"
printf '%s\n' "$0 $*" >> "$BASE/commands.log"
exec /file_storage01/home/weiyu/lanyi/envs/successful_phase05_20261007/bin/python "$1/probe_native_training.py"
