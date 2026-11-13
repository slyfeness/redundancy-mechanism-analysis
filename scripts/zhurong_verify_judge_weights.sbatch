#!/bin/bash
#SBATCH --job-name=redundancy-model-sha
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=12G
#SBATCH --time=02:00:00
set -euo pipefail
umask 077
BASE=/file_storage01/home/weiyu/lanyi
STORE="$BASE/projects/redundancy-judge-phase1"
RUN="$STORE/run-${1:?annotation job}"
OUTPUT="$STORE/model-check-$SLURM_JOB_ID"
mkdir -p "$OUTPUT"
cd "$BASE/models/gpt-oss-120b"
status=0
for shard in model-*.safetensors; do
    metadata=".cache/huggingface/download/$shard.metadata"
    expected=$(sed -n '2p' "$metadata")
    test "${#expected}" -eq 64
    before=$(stat --format='%n %s %Y' "$shard")
    got=$(sha256sum "$shard" | cut -d ' ' -f 1)
    after=$(stat --format='%n %s %Y' "$shard")
    result=MATCH
    if [[ "$expected" != "$got" || "$before" != "$after" ]] ||
       ! grep -Fxq -- "$before" "$RUN/judge_model_files.txt"; then
        result=MISMATCH
        status=1
    fi
    printf '%s  %s  %s\n' "$got" "$shard" "$result" | tee -a "$OUTPUT/weight_receipt.txt"
done
test "$(wc -l < "$OUTPUT/weight_receipt.txt")" -eq 15
exit "$status"
