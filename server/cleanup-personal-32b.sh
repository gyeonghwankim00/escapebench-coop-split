#!/usr/bin/env bash
# Only removes this project's personal 32B download, including its incomplete cache.
set -euo pipefail
if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
  cd "$(dirname "${BASH_SOURCE[0]}")/.."
else
  # SSH stdin mode works even when quota prevents uploading this script.
  cd "$HOME/escape-lab"
fi
root="$(pwd -P)"
if [[ "$root" != "$(cd "$HOME" && pwd -P)/escape-lab" ]]; then
  echo 'Run the server copy at ~/escape-lab/server/cleanup-personal-32b.sh.' >&2
  exit 2
fi
if [[ -L models || -L models/Qwen3-32B ]]; then
  echo 'Refusing cleanup: models or Qwen3-32B is a symlink.' >&2
  exit 2
fi
target="$root/models/Qwen3-32B"
if [[ ! -e "$target" ]]; then
  echo "Already absent: $target"
  exit 0
fi
echo "Personal 32B download only: $target"
du -sh -- "$target"
case "${1:-}" in
  --delete) rm -rf -- "$target"; echo "Removed: $target" ;;
  '') echo 'Preview only. Add --delete to remove this directory.' ;;
  *) echo 'Usage: bash server/cleanup-personal-32b.sh [--delete]' >&2; exit 2 ;;
esac
