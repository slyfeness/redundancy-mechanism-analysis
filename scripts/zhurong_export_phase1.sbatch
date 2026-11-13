#!/bin/bash
#SBATCH --job-name=redundancy-export
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=00:30:00
set -euo pipefail
umask 077
SOURCE="${1:?frozen source}"
ANNOTATION="${2:?annotation job}"
VERIFY="${3:?verification job}"
TEST_XML="${4:?local test receipt}"
BASE=/file_storage01/home/weiyu/lanyi
STORE="$BASE/projects/redundancy-judge-phase1"
RUN="$STORE/run-$ANNOTATION"
VERIFY_DIR="$STORE/check-$VERIFY"
OUTPUT="$STORE/export-$SLURM_JOB_ID"
PY="$BASE/envs/successful_phase05_20261007/bin/python"
export PYTHONPYCACHEPREFIX="$STORE/cache/pycache" PYTHONPATH="$SOURCE/src"
mkdir -p "$OUTPUT"
sacct -X -j "184746,184754,184768,184770,184778,184779,$ANNOTATION,$VERIFY" -P \
    -o JobID,JobName,Elapsed,Start,End,State,ExitCode,AllocTRES > "$OUTPUT/slurm.log"
for logfile in "pilot-184754" "pilot-184768" "full-$ANNOTATION"; do
    awk '/^20.* (batch_start|judge_ready|annotation_complete|workflow_complete)$/ {print}' \
        "$STORE/logs/$logfile.log" >> "$OUTPUT/slurm.log"
done
"$PY" "$SOURCE/scripts/export_phase1_acceptance.py" --run "$RUN" --inventory "$STORE/inventory-184746" \
    --verification "$VERIFY_DIR" --target "$OUTPUT/release" --test-report "$TEST_XML" --jobs "$OUTPUT/slurm.log"
cd "$OUTPUT/release"
sha256sum -- * > "$OUTPUT/SHA256SUMS"
