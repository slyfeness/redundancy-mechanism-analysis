#!/bin/bash
#SBATCH --job-name=bcplus-r4-prepare
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:20:00
set -euo pipefail
umask 077
export PYTHONDONTWRITEBYTECODE=1
date -u +'%FT%TZ batch_start'
exec /file_storage01/home/weiyu/lanyi/envs/successful_phase05_20261007/bin/python -u "$1/prepare.py" "$2" "$3"
