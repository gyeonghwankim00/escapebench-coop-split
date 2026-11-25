#!/usr/bin/env bash
# Install into one shared-storage Conda environment, inside a Slurm allocation.
set -euo pipefail
if [[ -z "${SLURM_JOB_ID:-}" ]]; then
  echo 'GPU 자원을 먼저 할당하세요: launch-shell 1 120' >&2
  exit 1
fi
cd "$(dirname "$0")/.."
env_dir="$PWD/.conda-env"
nvidia-smi
if [[ ! -x "$env_dir/bin/python" ]]; then
  if [[ -e "$env_dir" ]]; then
    echo "Incomplete Conda environment at $env_dir; inspect it before retrying." >&2
    exit 1
  fi
  if ! command -v conda >/dev/null 2>&1; then
    echo 'conda not found in PATH. Make the existing Conda installation available to the batch job.' >&2
    exit 1
  fi
  echo "Creating project Conda environment: $env_dir"
  conda create --yes --prefix "$env_dir" python=3.11 pip
fi
python="$env_dir/bin/python"
"$python" -c 'import sys; assert sys.version_info[:2] == (3, 11), "Project Conda environment requires Python 3.11."'
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$PWD/.cache/pip}"
"$python" -m pip install --upgrade pip
"$python" -m pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cu118
"$python" -m pip install -r requirements-model.txt
"$python" -m pip check
"$python" - <<'PY'
import torch
import transformers
import bitsandbytes
assert torch.cuda.is_available(), 'CUDA GPU unavailable; check allocation and NVIDIA driver.'
print('PyTorch:', torch.__version__, 'CUDA runtime:', torch.version.cuda)
print('Transformers:', transformers.__version__, 'bitsandbytes:', bitsandbytes.__version__)
print('GPU:', torch.cuda.get_device_name(0))
print('VRAM GiB:', round(torch.cuda.get_device_properties(0).total_memory / 2**30, 1))
PY
"$python" -m pip freeze > server/installed-packages.txt
touch "$env_dir/.escape-setup-complete"
printf '\nSetup finished: %s\n' "$env_dir"
