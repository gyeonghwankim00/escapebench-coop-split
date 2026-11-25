#!/usr/bin/env bash
# Run on the GSDS login node from ~/escape-lab. Submits games x conditions x
# models as independent 1-GPU jobs. Slurm runs as many at once as your per-user
# limit allows; the rest wait in the queue.
#
#   bash server/submit-matrix.sh                       # all 12 games, solo+coop, 8B+14B (18 jobs)
#   GAMES="game1-4-easy game1-5-easy game2-3-easy game3-1-easy" bash server/submit-matrix.sh
#   CONDITIONS=coop MODELS=8B bash server/submit-matrix.sh
#   PER_JOB_8B=4 PER_JOB_14B=2 ...                     # games per job (defaults shown)
#   SMOKE=1 bash server/submit-matrix.sh               # smoke check first; full jobs wait for it
#
# Output: outputs/matrix/<size>-<cond>_<games>/ ; the name lists the games, so a
# rerun with the same games resumes and a different set never collides.
# See what already exists first:  .conda-env/bin/python -m scripts.matrix_report --status
#
# Games inside one job share GPU batches, so job time ~ longest game's steps x
# batch time. Measured (8B, 4 episodes per batch): ~7.5 s/batch -> 4 games/job
# stays under ~8.5 h even at the 4,000-step cap. 14B is slower, hence 2 games/job.
set -euo pipefail
cd "$(dirname "$0")/.."
models="${MODELS:-8B 14B}"
conditions="${CONDITIONS:-solo coop}"
# Default order: longest worst case first, so long games share a job.
read -r -a games <<< "${GAMES:-game2-3-easy game3-1-easy game2-2-easy game1-4-easy game1-5-easy game2-5-easy game2-4-easy game3-2-easy game2-1-easy game1-2-easy game1-1-easy game1-3-easy}"
for g in "${games[@]}"; do
  [[ -f "data/roles/$g.json" ]] || { echo "Unknown game: $g" >&2; exit 2; }
done
dependency=()
if [[ -n ${SMOKE:-} ]]; then
  smoke=$(sbatch --parsable server/matrix-smoke.sbatch 8B)
  echo "smoke (8B, 1h): job $smoke -> matrix-smoke-$smoke.out"
  dependency=(--dependency="afterok:$smoke")
fi
for size in $models; do
  case "$size" in
    8B) per="${PER_JOB_8B:-4}" ;;
    14B) per="${PER_JOB_14B:-2}" ;;
    *) echo "Unknown model size: $size" >&2; exit 2 ;;
  esac
  for cond in $conditions; do
    case "$cond" in solo|coop) ;; *) echo "Unknown condition: $cond" >&2; exit 2 ;; esac
    for ((i = 0; i < ${#games[@]}; i += per)); do
      part=("${games[@]:i:per}")
      tag=$(printf '_%s' "${part[@]}" | sed -e 's/game//g' -e 's/-easy//g')
      out="outputs/matrix/g2-$size-$cond$tag"
      id=$(ESCAPE_OUT="$out" sbatch --parsable ${dependency[@]+"${dependency[@]}"} \
        server/matrix.sbatch "$size" "$cond" --games "${part[@]}")
      echo "$size $cond [${part[*]}]: job $id -> $out/"
    done
  done
done
echo 'Check: squeue -u "$USER" -o "%.10i %.20j %.8T %.10M %R"   (last column = why pending)'
