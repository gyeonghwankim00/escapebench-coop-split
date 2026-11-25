#!/usr/bin/env bash
#SBATCH --job-name=escape-original
#SBATCH --partition=P2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=11:30:00
#SBATCH --exclude=b12,b24,b27
#SBATCH --signal=USR1@120
#SBATCH --output=original-%j.out
#SBATCH --error=original-%j.err

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from escape-lab}"
echo "Job $SLURM_JOB_ID on $(hostname)"
if [[ ! -f .conda-env/.escape-setup-complete ]]; then
  srun bash server/setup.sh
fi
export HF_HOME="${HF_HOME:-$PWD/.cache/huggingface}"
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"
export PYTHONUNBUFFERED=1
# Diagnostics and inference run in the SAME Slurm step and Python process.
srun --ntasks=1 bash server/run-original.sh "$@"
