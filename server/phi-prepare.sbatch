#!/usr/bin/env bash
#SBATCH --job-name=escape-phi-prep
#SBATCH --partition=P2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=05:00:00
#SBATCH --exclude=b12,b24,b27
#SBATCH --signal=USR1@300
#SBATCH --output=nightly-phi-prep-%j.out
#SBATCH --error=nightly-phi-prep-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from escape-lab}"
[[ -f .conda-env/.escape-setup-complete ]] || { echo 'Existing Conda setup required' >&2; exit 2; }
export HF_HOME="${TMPDIR:-/tmp}/escape-hf-$USER-$SLURM_JOB_ID"
export HF_HUB_DISABLE_XET=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"
unset HF_HUB_OFFLINE
model=$(srun --ntasks=1 timeout --kill-after=60 10800 .conda-env/bin/python -m scripts.download_phi)
export HF_HUB_OFFLINE=1
base="/shared/s2/lab04/$(id -un)/escape-lab/outputs/nightly-v6"
smoke="$base/preflight-$SLURM_JOB_ID"
srun --ntasks=1 .conda-env/bin/python -m scripts.check_protocol --tokenizer "$model" \
  --output "$base/phi-protocol-check.json"
echo "Phi model: $model; pipeline check: $smoke"
srun --ntasks=1 .conda-env/bin/python -m scripts.run_matrix \
  --model "$model" --conditions solo coop --games game1-3-easy game2-4-easy \
  --interface original --quantization 4bit --max-batch 1 --max-steps 70 \
  --context-tokens 8192 --wall-seconds 3600 --output "$smoke"
.conda-env/bin/python -m scripts.check_matrix_smoke "$smoke" --require-action-output
cp "$smoke/smoke-check.json" "$base/phi-ready.json"
echo 'Phi preparation passed. Dependent Phi array can now start.'
