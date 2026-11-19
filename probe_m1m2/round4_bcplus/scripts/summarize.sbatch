#!/bin/bash
#SBATCH --job-name=bcplus-r4-signals
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=00:30:00
set -euo pipefail
umask 077
export PYTHONDONTWRITEBYTECODE=1
date -u +'%FT%TZ batch_start'
BASE=/file_storage01/home/weiyu/lanyi
MODEL="$BASE/models/Qwen3.5-4B--851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
exec "$BASE/envs/successful_phase05_20261007/bin/python" -u "$1/summarize.py" "$2" "$3" "$MODEL/tokenizer.json" "$4/analysis-$SLURM_JOB_ID" "${@:5}"
