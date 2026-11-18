#!/bin/bash
#SBATCH --job-name=probe-m1m2-round2
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
exec /file_storage01/home/weiyu/lanyi/envs/successful_phase05_20261007/bin/python "$1/analyze_round2.py"
