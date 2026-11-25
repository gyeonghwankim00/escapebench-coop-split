#!/usr/bin/env bash
# One Qwen array slot, plus Phi preparation OR one Phi array slot: at most two GPUs.
set -euo pipefail
cd "$(dirname "$0")/.."
dry=0
phi_only=0
while (( $# )); do
  case "$1" in
    --dry-run) dry=1 ;;
    --phi-only) phi_only=1 ;;
    *) echo 'Usage: bash server/submit-nightly.sh [--dry-run] [--phi-only]' >&2; exit 2 ;;
  esac
  shift
done
submit() {
  if (( dry )); then
    printf 'sbatch ' >&2; printf '%q ' "$@" >&2; printf '\n' >&2
    echo DRYRUN
  else
    sbatch --parsable "$@"
  fi
}
if (( ! dry )); then
  [[ -f .conda-env/.escape-setup-complete && -f models/Qwen3-14B/config.json ]] || {
    echo 'Need existing Conda environment and models/Qwen3-14B.' >&2; exit 2;
  }
  lab="/shared/s2/lab04/$(id -un)/escape-lab"
  mkdir -p "$lab/outputs/nightly-v6"
  [[ -w "$lab" ]] || { echo 'Shared personal directory is not writable.' >&2; exit 2; }
  active=$(squeue --noheader --user="$(id -un)" --format='%j')
  while IFS= read -r name; do
    case "$name" in escape-nightly|escape-phi-prep)
      echo 'Existing nightly/preparation jobs are active or queued. Do not submit duplicates.' >&2; exit 2 ;;
    esac
  done <<< "$active"
  if (( ! phi_only )); then
    # CPU tokenizer + scripted environment replay only; no model weights or GPU inference.
    .conda-env/bin/python -m scripts.check_protocol --tokenizer models/Qwen3-14B \
      --output "$lab/outputs/nightly-v6/qwen-protocol-check.json"
  fi
fi
if (( ! phi_only )); then
  qwen=$(submit server/nightly.sbatch qwen14); qwen=${qwen%%;*}
  echo "Qwen array: $qwen (24 array slots / 22 episodes, one GPU at a time)"
fi
prep=$(submit server/phi-prepare.sbatch); prep=${prep%%;*}
echo "Phi download + pipeline check: $prep"
phi=$(submit --dependency="afterok:$prep" --kill-on-invalid-dep=yes server/nightly.sbatch phi14)
phi=${phi%%;*}
echo "Phi array: $phi (24 array slots / 22 episodes, starts only after preparation succeeds)"
echo 'Settings: 11 eligible easy games (1-4 skipped), Solo/Peer, original interface, batch=1, max 500 team actions.'
echo 'Results: /shared/s2/lab04/<account>/escape-lab/outputs/nightly-v6'
echo 'Status: squeue -u "$USER". Finished episodes are skipped on matching resubmission.'
