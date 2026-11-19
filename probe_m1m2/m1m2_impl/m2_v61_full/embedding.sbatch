#!/bin/bash
#SBATCH --job-name=m2-v61-embed
#SBATCH --partition=gre
#SBATCH --account=professors
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=24
#SBATCH --mem=384G
#SBATCH --time=48:00:00
set -euo pipefail
umask 077
CODE="$1"
PREP="$2"
BASE=/file_storage01/home/weiyu/lanyi
OUT="$(dirname "$PREP")/m2-v61-full-embed-$SLURM_JOB_ID"
mkdir -m 700 "$OUT"
source "$CODE/local_env.sh" "$OUT"
date -u +'%FT%TZ embedding_batch_start'
"$PY" -m torch.distributed.run --standalone --nproc-per-node=4 "$CODE/embed.py" first \
    --base "$BASE" --prep "$PREP" --out "$OUT"
date -u +'%FT%TZ embedding_complete'
