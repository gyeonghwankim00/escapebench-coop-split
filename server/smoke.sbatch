#!/usr/bin/env bash
#SBATCH --job-name=escape-smoke
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --signal=USR1@60
#SBATCH --output=escape-%j.out
#SBATCH --error=escape-%j.err

set -euo pipefail
# Submit from the project root; choose your allowed partition with sbatch -p ...
cd "${SLURM_SUBMIT_DIR:?Submit this job from the escape-lab project directory}"
srun bash server/run.sh "$@"
