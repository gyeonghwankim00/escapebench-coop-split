#!/usr/bin/env bash
#SBATCH --job-name=escape-nightly
#SBATCH --partition=P2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=11:30:00
#SBATCH --array=0-23%1
#SBATCH --exclude=b12,b24,b27
#SBATCH --signal=USR1@300
#SBATCH --output=nightly-%A_%a.out
#SBATCH --error=nightly-%A_%a.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from escape-lab}"
model="${1:?Use qwen14 or phi14}"
case "$model" in qwen14|phi14) ;; *) exit 2 ;; esac
[[ -f .conda-env/.escape-setup-complete ]] || { echo 'Existing Conda setup required' >&2; exit 2; }
export HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"
export HF_HOME="${TMPDIR:-/tmp}/escape-hf-$USER-$SLURM_JOB_ID"
base="/shared/s2/lab04/$(id -un)/escape-lab/outputs/nightly-v6"
if [[ "$model" == phi14 && ! -f "$base/phi-ready.json" ]]; then
  echo 'Phi preflight is missing. Use submit-nightly.sh first.' >&2; exit 2
fi
mkdir -p "$base"
echo "Job $SLURM_JOB_ID array index $SLURM_ARRAY_TASK_ID: $model -> $base"
srun --ntasks=1 .conda-env/bin/python -m scripts.run_nightly \
  --model "$model" --index "${SLURM_ARRAY_TASK_ID:?}" --output-root "$base"
