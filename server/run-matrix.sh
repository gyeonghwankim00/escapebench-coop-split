#!/usr/bin/env bash
# Called by server/matrix.sbatch and server/matrix-smoke.sbatch inside srun.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -z ${SLURM_JOB_ID:-} ]]; then
  echo 'Use sbatch server/matrix.sbatch to allocate a GPU first.' >&2
  exit 1
fi
python="$PWD/.conda-env/bin/python"
if ! "$python" -c 'import yaml; assert yaml.__version__ == "6.0.2"' 2>/dev/null; then
  "$python" -m pip install -r requirements-original.txt
fi
exec "$python" -m scripts.run_matrix "$@"
