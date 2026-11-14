#!/bin/bash
set -euo pipefail
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}src"
CONFIG="${1:-configs/phase1.yaml}"
shift || true
python -m redundancy_judge.cli annotate --config "$CONFIG" "$@"
