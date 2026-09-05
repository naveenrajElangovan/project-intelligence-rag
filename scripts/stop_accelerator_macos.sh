#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIRECTORY="$(cd "${SCRIPT_DIRECTORY}/.." && pwd)"
PID_FILE="${PROJECT_DIRECTORY}/.run/accelerator.pid"

if [[ ! -f "${PID_FILE}" ]]; then
  echo "No managed MPS accelerator is running."
  exit 0
fi

pid="$(<"${PID_FILE}")"
command_line="$(ps -p "${pid}" -o command= 2>/dev/null || true)"
if [[ -n "${command_line}" && "${command_line}" == *"${PROJECT_DIRECTORY}"* ]]; then
  kill "${pid}" 2>/dev/null || true
  for _ in {1..20}; do
    kill -0 "${pid}" 2>/dev/null || break
    sleep 0.1
  done
fi
rm -f "${PID_FILE}"
echo "Managed MPS accelerator stopped."
