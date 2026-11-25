#!/usr/bin/env bash
#SBATCH --job-name=escape-cohort
#SBATCH --partition=P2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=96G
#SBATCH --time=11:30:00
#SBATCH --array=0-47%2
#SBATCH --exclude=b12,b24,b27
#SBATCH --signal=USR1@300
#SBATCH --output=cohort-%A_%a.out
#SBATCH --error=cohort-%A_%a.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from escape-lab}"
[[ -f .conda-env/.escape-setup-complete ]] || { echo 'Existing Conda setup required' >&2; exit 2; }
export HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"
export HF_HOME="${TMPDIR:-/tmp}/escape-hf-$USER-$SLURM_JOB_ID"
account=$(id -un)
out="/shared/s2/lab04/$account/escape-lab/outputs/cohort-v2"
mkdir -p "$out"
# One complete episode per allocation; identical batch=1 for both models.
# Infrastructure interruption is saved by run_matrix (exit 75), not scored as failure.
srun --ntasks=1 .conda-env/bin/python -m scripts.run_cohort \
  --index "${SLURM_ARRAY_TASK_ID:?}" --output-root "$out"
