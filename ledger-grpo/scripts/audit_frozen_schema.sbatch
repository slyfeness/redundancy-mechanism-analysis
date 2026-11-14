#!/bin/bash
#SBATCH --job-name=ledger-native-schema
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=00:05:00
#SBATCH --output=/file_storage01/home/weiyu/lanyi/projects/ledger-grpo-pilot/preflight/group-audit-20261111/schema-%j.out
#SBATCH --error=/file_storage01/home/weiyu/lanyi/projects/ledger-grpo-pilot/preflight/group-audit-20261111/schema-%j.err
set -euo pipefail
umask 077
export PYTHONDONTWRITEBYTECODE=1 CUDA_VISIBLE_DEVICES=''
unset PYTHONPATH JUDGE_API_KEY
control=/persist_data/home/weiyu/lanyi/projects/ledger-grpo-pilot/control/group-audit-20261111
source_base=/file_storage01/home/weiyu/lanyi/projects/browsecomp-qwen35-9b-grpo-smoke/runs
output=/file_storage01/home/weiyu/lanyi/projects/ledger-grpo-pilot/preflight/group-audit-20261111
exec /file_storage01/home/weiyu/lanyi/envs/successful_phase05_20261007/bin/python "$control/audit_frozen_groups_schema_v2.py" \
  --source-run "$source_base/grpo-stability-181915" --source-code "$source_base/stability-tenstep-v4" \
  --output-dir "$output" --schema-only "$source_base/grpo-stability-181915/step-08/rollout-1/trajectories/1003__rep1/trajectory.json"
