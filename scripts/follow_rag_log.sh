#!/usr/bin/env bash
# Stream the RAG container's stage telemetry into .run/rag-debug.log so it can be
# read at any time without re-running a docker command. Idempotent: re-running
# replaces the previous follower. The container is recreated by
# prepare_and_start_local_app.sh, so run this again after each rebuild.
set -euo pipefail

SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIRECTORY="$(cd "${SCRIPT_DIRECTORY}/.." && pwd)"
RUNTIME_DIRECTORY="${PROJECT_DIRECTORY}/.run"
LOG_FILE="${RUNTIME_DIRECTORY}/rag-debug.log"
PID_FILE="${RUNTIME_DIRECTORY}/rag-log-follower.pid"

mkdir -p "${RUNTIME_DIRECTORY}"

if [[ -f "${PID_FILE}" ]] && kill -0 "$(<"${PID_FILE}")" 2>/dev/null; then
  kill "$(<"${PID_FILE}")" 2>/dev/null || true
fi
rm -f "${PID_FILE}"

container="$(docker ps -q --filter ancestor=project-intelligence-rag:0.1.0 | head -1)"
if [[ -z "${container}" ]]; then
  echo "No running project-intelligence-rag container found." >&2
  exit 1
fi

: > "${LOG_FILE}"
nohup docker logs -f --tail 200 "${container}" >> "${LOG_FILE}" 2>&1 &
printf '%s' "$!" > "${PID_FILE}"
echo "Following container ${container} into ${LOG_FILE} (pid $(<"${PID_FILE}"))."
