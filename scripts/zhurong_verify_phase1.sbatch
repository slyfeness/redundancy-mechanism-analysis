#!/bin/bash
#SBATCH --job-name=redundancy-check
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=12
#SBATCH --mem=96G
#SBATCH --time=03:00:00
set -euo pipefail
umask 077
SOURCE="${1:?frozen source}"
BASE=/file_storage01/home/weiyu/lanyi
STORE="$BASE/projects/redundancy-judge-phase1"
RUN="$STORE/run-${2:?annotation job}"
OUTPUT="$STORE/check-$SLURM_JOB_ID"
PY="$BASE/envs/successful_phase05_20261007/bin/python"
mkdir -p "$OUTPUT" "$STORE/cache/pycache"
export PYTHONPYCACHEPREFIX="$STORE/cache/pycache" PYTHONPATH="$SOURCE/src"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
"$PY" "$SOURCE/scripts/check_phase1_run.py" --run "$RUN/real" --receipt "$OUTPUT/mechanical.json"
if [[ "${3:-pilot}" == pilot ]]; then exit 0; fi
"$PY" "$SOURCE/scripts/index_browsecomp.py" --reports-root "$BASE/projects/新实验/reports" +    --output "$OUTPUT/inventory-after"
mkdir -p "$OUTPUT/replay/real"
ln -s "$RUN/real/model_cache" "$OUTPUT/replay/real/model_cache"
"$PY" - "$RUN/config.json" "$OUTPUT" <<'PYTHON'
import json
from pathlib import Path
import sys
cfg = json.loads(Path(sys.argv[1]).read_bytes())
out = Path(sys.argv[2])
cfg.update(output_dir=str(out / "replay"), run_dir=str(out / "replay/real"))
(out / "replay-config.json").write_text(json.dumps(cfg))
PYTHON
for command in annotate export-review audit reward-preview; do
    extra=()
    if [[ "$command" == annotate ]]; then extra+=(--split all --resume --replay-only); fi
    "$PY" -m redundancy_judge.cli "$command" --config "$OUTPUT/replay-config.json" "${extra[@]}"
done
"$PY" "$SOURCE/scripts/compare_phase1_replay.py" --original "$RUN" --verification "$OUTPUT"
