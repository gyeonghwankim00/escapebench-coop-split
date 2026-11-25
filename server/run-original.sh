#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -z ${SLURM_JOB_ID:-} ]]; then
  echo 'Use sbatch server/original.sbatch to allocate a GPU first.' >&2
  exit 1
fi
python="$PWD/.conda-env/bin/python"
if ! "$python" -c 'import yaml; assert yaml.__version__ == "6.0.2"'; then
  "$python" -m pip install -r requirements-original.txt
fi
exec "$python" -m scripts.run_original --model "$PWD/models/Qwen3-14B" "$@"
