#!/usr/bin/env bash
# On the login node: one 14B smoke, then two single-GPU jobs gated by its success.
# Repeating a RUN_TAG reuses saved episodes (matching code/settings required).
set -euo pipefail
cd "$(dirname "$0")/.."
dry=0
if [[ ${1:-} == --dry-run ]]; then dry=1; shift; fi
[[ $# == 0 ]] || { echo 'Usage: bash server/submit-pilot.sh [--dry-run]' >&2; exit 2; }
submit() {
  if (( dry )); then
    printf 'ESCAPE_OUT=%q sbatch ' "${ESCAPE_OUT:-}" >&2
    printf '%q ' "$@" >&2
    printf '\n' >&2
    echo DRYRUN
  else
    sbatch "$@"
  fi
}
tag="${RUN_TAG:-pilot-v3-g2-14B}"
[[ "$tag" =~ ^[A-Za-z0-9_-]+$ ]] || { echo 'Invalid RUN_TAG' >&2; exit 2; }
(( dry )) || [[ -f models/Qwen3-14B/config.json && -f .conda-env/.escape-setup-complete ]] || {
  echo 'Need models/Qwen3-14B and the existing .conda-env setup first.' >&2; exit 2;
}
smoke=$(submit --parsable server/matrix-smoke.sbatch 14B)
smoke=${smoke%%;*}
echo "14B smoke: $smoke (matrix-smoke-$smoke.out/.err)"
main=$(ESCAPE_OUT="outputs/matrix/$tag-main" submit --parsable \
  --dependency="afterok:$smoke" --kill-on-invalid-dep=yes server/matrix.sbatch 14B both \
  --games game1-1-easy game2-4-easy --max-batch 4)
control=$(ESCAPE_OUT="outputs/matrix/$tag-control" submit --parsable \
  --dependency="afterok:$smoke" --kill-on-invalid-dep=yes server/matrix.sbatch 14B both \
  --games game1-3-easy --max-batch 2)
echo "Main (mirror/lab, Solo+Peer): $main -> outputs/matrix/$tag-main"
echo "Control (billiards, Solo+Peer): $control -> outputs/matrix/$tag-control"
echo 'If smoke fails, dependent jobs are cancelled. Check logs before resubmitting.'
echo 'Status: squeue -u "$USER"'
