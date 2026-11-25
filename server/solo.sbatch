#!/usr/bin/env bash
#SBATCH --job-name=escape-solo
#SBATCH --partition=P2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --exclude=b27
#SBATCH --output=solo-%j.out
#SBATCH --error=solo-%j.err

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the project directory}"
echo "Job $SLURM_JOB_ID on $(hostname)"
# Install once in the shared project directory, on an allocated node.
if [[ ! -f .conda-env/.escape-setup-complete ]]; then
  srun bash server/setup.sh
fi
# Additional arguments may override the defaults, e.g. --max-steps 2.
srun bash server/run.sh --solo --max-steps 150 --history-turns 30 "$@"
