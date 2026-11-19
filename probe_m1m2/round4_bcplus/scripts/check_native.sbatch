#!/bin/bash
#SBATCH --job-name=bcplus-r4-native-check
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:15:00
set -euo pipefail
umask 077
export PYTHONDONTWRITEBYTECODE=1
BASE=/file_storage01/home/weiyu/lanyi
exec "$BASE/envs/successful_phase05_20261007/bin/python" -u "$1/check_native.py" "$2" \
    "$BASE/projects/q4j/run-190197/rollout" "$BASE/models/Qwen3.5-4B--851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a/tokenizer.json" \
    "$3/native-check-$SLURM_JOB_ID.json"
