#!/usr/bin/env bash
# Run on the local computer. Password entry is handled by SSH in your terminal.
set -euo pipefail
cd "$(dirname "$0")/.."
ESCAPE_REMOTE="gyeonghwankim@147.47.200.188"
ESCAPE_PORT="${ESCAPE_PORT:-22555}"
if [[ ! "$ESCAPE_PORT" =~ ^[0-9]+$ ]]; then
  echo 'ESCAPE_PORT must be numeric.' >&2
  exit 1
fi
ssh -p "$ESCAPE_PORT" "$ESCAPE_REMOTE" 'mkdir -p ~/escape-lab'
# Explicit allowlist: no credentials, local environments, outputs, or IDE settings.
rsync -av --exclude='__pycache__' --exclude='*.pyc' --exclude='installed-packages.txt' \
  -e "ssh -p $ESCAPE_PORT" \
  scripts data tests server experiments vendor web app.py README.md requirements-build.txt requirements-model.txt requirements-original.txt \
  "$ESCAPE_REMOTE:escape-lab/"
