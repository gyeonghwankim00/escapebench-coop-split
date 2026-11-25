#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ${1:-} == --dry-run ]]; then
  echo 'sbatch server/state-probes.sbatch 14B'
  echo 'sbatch server/state-probes.sbatch 32B'
  exit 0
fi
[[ $# == 0 ]] || { echo 'Usage: bash server/submit-state-probes.sh [--dry-run]' >&2; exit 2; }
[[ -f data/state_probes/manifest.json && -f models/Qwen3-14B/config.json ]] || {
  echo 'Upload the state probes and provide the existing 14B model first.' >&2; exit 2;
}
sbatch server/state-probes.sbatch 14B
sbatch server/state-probes.sbatch 32B
