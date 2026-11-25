#!/usr/bin/env bash
#SBATCH --job-name=escape-smoke
#SBATCH --partition=P2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --exclude=b12,b24,b27
#SBATCH --signal=USR1@120
#SBATCH --output=matrix-smoke-%j.out
#SBATCH --error=matrix-smoke-%j.err
#
# Pipeline and throughput check before long runs: Qwen3-8B or 14B, solo+coop,
# two games, 70 steps each (can reach the 50-step help trigger), batched together.
# Usage: sbatch server/matrix-smoke.sbatch [8B|14B]
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from escape-lab}"
size="${1:-8B}"
model="$PWD/models/Qwen3-$size"
out="outputs/matrix/smoke-$size-$SLURM_JOB_ID"
echo "Job $SLURM_JOB_ID on $(hostname): smoke Qwen3-$size -> $out"
if [[ ! -f .conda-env/.escape-setup-complete ]]; then
  srun bash server/setup.sh
fi
export HF_HOME="${HF_HOME:-$PWD/.cache/huggingface}"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"
export PYTHONUNBUFFERED=1
srun --ntasks=1 bash server/run-matrix.sh --model "$model" --conditions solo coop \
  --games game1-3-easy game2-4-easy --max-steps 70 --wall-seconds 3000 --output "$out"
cat "$out/report.md"
.conda-env/bin/python -m scripts.check_matrix_smoke "$out"
