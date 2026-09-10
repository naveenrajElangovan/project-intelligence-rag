#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIRECTORY="$(cd "${SCRIPT_DIRECTORY}/.." && pwd)"
KEY_FILE="${PROJECT_DIRECTORY}/.run/accelerator.key"

if [[ -z "${PI_RAG_INTERNAL_API_KEY:-}" ]]; then
  if [[ ! -s "${KEY_FILE}" ]]; then
    echo "The accelerator runtime credential is missing." >&2
    exit 1
  fi
  export PI_RAG_INTERNAL_API_KEY="$(<"${KEY_FILE}")"
fi
cd "${PROJECT_DIRECTORY}"
exec "${PROJECT_DIRECTORY}/.venv/bin/uvicorn" app.inference_api:app \
  --host 0.0.0.0 --port 8004
