#!/usr/bin/env bash
#SBATCH --job-name=escape-solo-all
#SBATCH --partition=P2
#SBATCH --array=0-7%1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --exclude=b27
#SBATCH --output=solo-%A_%a.out
#SBATCH --error=solo-%A_%a.err

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the project directory}"
datasets=(
  data/pilot/01_mirror_workshop/environment.json
  data/pilot/02_records_billiards/environment.json
  data/pilot/03_cabinet_mechanism/environment.json
  data/pilot/04_hospital_elevator/environment.json
  data/pilot/05_shop_offices/environment.json
  data/pilot/06_basement_laboratory/environment.json
  data/pilot/07_van_escape/environment.json
  data/pilot/08_laundry_escape/environment.json
)
dataset="${datasets[$SLURM_ARRAY_TASK_ID]}"
echo "Array $SLURM_ARRAY_JOB_ID task $SLURM_ARRAY_TASK_ID job $SLURM_JOB_ID on $(hostname)"
echo "Dataset: $dataset"
if [[ ! -f .conda-env/.escape-setup-complete ]]; then
  srun bash server/setup.sh
fi
srun bash server/run.sh --solo --dataset "$dataset" --max-steps 150 --history-turns 30 "$@"
