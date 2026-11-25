#!/usr/bin/env bash
#SBATCH --job-name=escape-probes
#SBATCH --partition=P2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=96G
#SBATCH --time=11:30:00
#SBATCH --exclude=b12,b24,b27
#SBATCH --signal=USR1@300
#SBATCH --output=probes-%j.out
#SBATCH --error=probes-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from escape-lab}"
size="${1:?Use 14B or 32B}"
case "$size" in 14B|32B) ;; *) exit 2 ;; esac
[[ -f .conda-env/.escape-setup-complete ]] || { echo 'Existing Conda setup required' >&2; exit 2; }
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"
export PYTHONUNBUFFERED=1
# Cache on node-local scratch; model files themselves go to the selected storage.
export HF_HOME="${TMPDIR:-/tmp}/escape-hf-$USER-$SLURM_JOB_ID"
export HF_HUB_DISABLE_XET=1
unset HF_HUB_OFFLINE
model="$PWD/models/Qwen3-$size"
if [[ $size == 32B ]]; then
  echo 'Resuming 32B directly in shared storage (download limit: 4 hours)'
  model=$(srun --ntasks=1 timeout --kill-after=60 14400 .conda-env/bin/python -m scripts.download_32b --storage shared)
fi
[[ -f "$model/config.json" ]] || { echo "Invalid/incomplete model path: $model" >&2; exit 2; }
export HF_HUB_OFFLINE=1
# If personal quota was exhausted, write probe results in the same private lab subtree.
out="$PWD/outputs/state-probes-v1-$size"
if [[ $model == /shared/s2/lab04/* ]]; then
  out="$(dirname "$(dirname "$model")")/outputs/state-probes-v1-$size"
fi
echo "Job $SLURM_JOB_ID, model=$model, results=$out"
srun --ntasks=1 .conda-env/bin/python -m scripts.run_state_probes \
  --model "$model" --output "$out" --wall-seconds 21600
