#!/usr/bin/env bash
#SBATCH --job-name=escape-matrix
#SBATCH --partition=P2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=11:30:00
#SBATCH --exclude=b12,b24,b27
#SBATCH --signal=USR1@300
#SBATCH --output=matrix-%j.out
#SBATCH --error=matrix-%j.err
#
# Usage (from ~/escape-lab):  sbatch server/matrix.sbatch 8B|14B solo|coop|both [run_matrix args]
# Output: outputs/matrix/<size>-<condition>/ (fixed name, so resubmitting resumes).
# If the runner stops at its 11h10m wall limit (exit 75), this job resubmits itself
# with the same arguments, up to ESCAPE_MAX_ATTEMPTS (default 4) jobs in total.
set -uo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from escape-lab}"
size="${1:?model size: 8B or 14B}"
cond="${2:?condition: solo, coop or both}"
shift 2
case "$size" in 8B|14B) ;; *) echo "Unknown model size: $size" >&2; exit 2 ;; esac
case "$cond" in
  solo|coop) conditions="$cond" ;;
  both) conditions="solo coop" ;;
  *) echo "Unknown condition: $cond" >&2; exit 2 ;;
esac
model="$PWD/models/Qwen3-$size"
out="${ESCAPE_OUT:-outputs/matrix/g2-$size-$cond}"
attempt="${ESCAPE_ATTEMPT:-1}"
max_attempts="${ESCAPE_MAX_ATTEMPTS:-4}"
echo "Job $SLURM_JOB_ID on $(hostname): Qwen3-$size, $cond, attempt $attempt/$max_attempts -> $out"
if [[ ! -f "$model/config.json" ]]; then
  echo "Model not found: $model" >&2
  exit 2
fi
if [[ ! -f .conda-env/.escape-setup-complete ]]; then
  echo 'Conda environment missing. Run server/setup.sh in a GPU allocation first.' >&2
  exit 2
fi
export HF_HOME="${HF_HOME:-$PWD/.cache/huggingface}"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"
export PYTHONUNBUFFERED=1
status=0
# shellcheck disable=SC2086
srun --ntasks=1 bash server/run-matrix.sh --model "$model" --conditions $conditions --output "$out" "$@" || status=$?
echo "run_matrix exit status: $status"
if [[ $status -eq 75 ]]; then
  if (( attempt < max_attempts )); then
    next=$(sbatch --parsable --export=ALL,ESCAPE_ATTEMPT=$((attempt + 1)),ESCAPE_OUT="$out" \
      server/matrix.sbatch "$size" "$cond" "$@")
    echo "Unfinished episodes remain; resubmitted as job $next"
  else
    echo "Reached $max_attempts attempts. Resume manually: sbatch server/matrix.sbatch $size $cond" >&2
  fi
fi
exit "$status"
