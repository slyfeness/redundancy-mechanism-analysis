#!/bin/bash
#SBATCH --job-name=ledger-group-audit
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --output=/file_storage01/home/weiyu/lanyi/projects/ledger-grpo-pilot/preflight/group-audit-20261111/audit-%j.out
#SBATCH --error=/file_storage01/home/weiyu/lanyi/projects/ledger-grpo-pilot/preflight/group-audit-20261111/audit-%j.err
set -euo pipefail
umask 077
export PYTHONDONTWRITEBYTECODE=1
export CUDA_VISIBLE_DEVICES=''
unset PYTHONPATH JUDGE_API_KEY
control=/persist_data/home/weiyu/lanyi/projects/ledger-grpo-pilot/control/group-audit-20261111
source_base=/file_storage01/home/weiyu/lanyi/projects/browsecomp-qwen35-9b-grpo-smoke/runs
output=/file_storage01/home/weiyu/lanyi/projects/ledger-grpo-pilot/preflight/group-audit-20261111
exec /file_storage01/home/weiyu/lanyi/envs/successful_phase05_20261007/bin/python "$control/audit_frozen_groups.py" \
  --source-run "$source_base/grpo-stability-181915" \
  --source-code "$source_base/stability-tenstep-v4" --output-dir "$output"
