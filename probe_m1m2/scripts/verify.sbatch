#!/bin/bash
#SBATCH --job-name=probe-m1m2-verify
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:10:00
set -euo pipefail
umask 077
export PROBE_OUT=/file_storage01/home/weiyu/lanyi/projects/deepsearch-world-pilot/probe_m1m2
export PYTHONDONTWRITEBYTECODE=1
printf '%s\n' "$0 $*" >> "$PROBE_OUT/commands.log"
/file_storage01/home/weiyu/lanyi/envs/successful_phase05_20261007/bin/python "$1/verify_and_finalize.py"
