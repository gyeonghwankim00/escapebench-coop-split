#!/usr/bin/env bash
#SBATCH --job-name=escape-two-models
#SBATCH --partition=P2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=11:30:00
#SBATCH --exclude=b27
#SBATCH --signal=USR1@120
#SBATCH --output=experiment-%j.out
#SBATCH --error=experiment-%j.err

set -euo pipefail
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != '--14b-only' ) ]]; then
  echo 'Usage: sbatch server/experiment-two-models.sbatch [--14b-only]' >&2
  exit 2
fi
cd "${SLURM_SUBMIT_DIR:?Submit from the escape-lab project directory}"
echo "Job $SLURM_JOB_ID on $(hostname)"
if [[ ! -f .conda-env/.escape-setup-complete ]]; then
  srun bash server/setup.sh
fi
export HF_HOME="${HF_HOME:-$PWD/.cache/huggingface}"
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"
export PYTHONUNBUFFERED=1
results="$PWD/outputs/two-models-$SLURM_JOB_ID"
mkdir -p "$results"
echo "Results directory: $results"
if [[ ${1:-} != '--14b-only' ]]; then
  echo 'Stage 1/3: Qwen3-8B'
  srun .conda-env/bin/python -m scripts.run_experiment \
    --model "$PWD/models/Qwen3-8B" --output "$results/8B" --wall-seconds 16200
fi
echo 'Stage 2/3: download Qwen3-14B (up to 90 minutes)'
srun timeout 5400 .conda-env/bin/python -m scripts.download_14b
echo 'Stage 3/3: Qwen3-14B'
srun .conda-env/bin/python -m scripts.run_experiment \
  --model "$PWD/models/Qwen3-14B" --output "$results/14B" --wall-seconds 16200
echo "Both experiments finished. Results: $results"
