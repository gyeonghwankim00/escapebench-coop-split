#!/usr/bin/env bash
# Submit from ~/escape-lab on login1. Existing original results stay untouched.
set -euo pipefail
cd "$(dirname "$0")/.."
dry=0
if [[ ${1:-} == --dry-run ]]; then dry=1; shift; fi
[[ $# == 0 ]] || { echo 'Usage: bash server/submit-interface-diagnostic.sh [--dry-run]' >&2; exit 2; }
submit() {
  if (( dry )); then
    printf 'ESCAPE_OUT=%q sbatch ' "$ESCAPE_OUT"
    printf '%q ' "$@"
    printf '\n'
  else
    sbatch "$@"
  fi
}
(( dry )) || [[ -f models/Qwen3-14B/config.json && -f .conda-env/.escape-setup-complete ]] || {
  echo 'Existing 14B model and Conda environment required.' >&2; exit 2;
}
ESCAPE_OUT=outputs/matrix/diagnostic-v3-g2-14B-move-labels \
  submit server/matrix.sbatch 14B both --games game2-4-easy --max-batch 2 --interface move_labels
ESCAPE_OUT=outputs/matrix/diagnostic-v3-g2-14B-action-labels \
  submit server/matrix.sbatch 14B both --games game1-3-easy --max-batch 2 --interface action_labels
