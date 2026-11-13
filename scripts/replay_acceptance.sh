#!/bin/bash
set -euo pipefail
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}src"
CONFIG="${1:?phase1 config with authorized cached data}"
python -m pytest tests -q
python -m redundancy_judge.cli annotate --config "$CONFIG" --split all --resume --replay-only
python -m redundancy_judge.cli export-review --config "$CONFIG"
python -m redundancy_judge.cli audit --config "$CONFIG"
python -m redundancy_judge.cli reward-preview --config "$CONFIG"
