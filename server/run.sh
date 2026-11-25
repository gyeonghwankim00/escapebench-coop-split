#!/usr/bin/env bash
set -euo pipefail
if [[ -z "${SLURM_JOB_ID:-}" ]]; then
  echo '로그인 노드에서는 실행할 수 없습니다. launch-shell 또는 sbatch를 사용하세요.' >&2
  exit 1
fi
cd "$(dirname "$0")/.."
if [[ ! -x .conda-env/bin/python || ! -f .conda-env/.escape-setup-complete ]]; then
  echo 'GPU 할당 안에서 bash server/setup.sh 를 먼저 실행하세요.' >&2
  exit 1
fi
export HF_HOME="${HF_HOME:-$PWD/.cache/huggingface}"
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"
export PYTHONUNBUFFERED=1
# Leave CUDA_VISIBLE_DEVICES exactly as Slurm assigned it.
exec .conda-env/bin/python -m scripts.run_model "$@"
