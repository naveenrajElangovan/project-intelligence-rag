#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIRECTORY="$(cd "${SCRIPT_DIRECTORY}/.." && pwd)"
RUNTIME_DIRECTORY="${PROJECT_DIRECTORY}/.run"
PID_FILE="${RUNTIME_DIRECTORY}/accelerator.pid"
LOG_FILE="${RUNTIME_DIRECTORY}/accelerator.log"
KEY_FILE="${RUNTIME_DIRECTORY}/accelerator.key"
ENV_FILE="${PROJECT_DIRECTORY}/.env"

read_env_value() {
  local requested_key="$1" line key
  [[ -f "${ENV_FILE}" ]] || return 0
  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ "${line}" == \#* ]] && continue
    key="${line%%=*}"
    if [[ "${key}" == "${requested_key}" ]]; then
      line="${line#*=}"
      printf '%s' "${line%$'\r'}"
      return 0
    fi
  done < "${ENV_FILE}"
}

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "The local accelerator requires Apple Silicon macOS." >&2
  exit 1
fi
if [[ ! -x "${PROJECT_DIRECTORY}/.venv/bin/python" ]]; then
  echo "The RAG virtual environment is unavailable." >&2
  exit 1
fi
if ! "${PROJECT_DIRECTORY}/.venv/bin/python" -c \
  'import torch,sys; sys.exit(0 if torch.backends.mps.is_available() else 1)'; then
  echo "Apple MPS is unavailable; refusing CPU fallback." >&2
  exit 1
fi

mkdir -p "${RUNTIME_DIRECTORY}"
chmod 0700 "${RUNTIME_DIRECTORY}"
api_key="${PI_RAG_INTERNAL_API_KEY:-$(read_env_value PI_RAG_INTERNAL_API_KEY)}"
if [[ -z "${api_key}" && -s "${KEY_FILE}" ]]; then
  api_key="$(<"${KEY_FILE}")"
fi
if [[ -z "${api_key}" ]]; then
  umask 077
  openssl rand -hex 32 >"${KEY_FILE}"
  api_key="$(<"${KEY_FILE}")"
fi
export PI_RAG_INTERNAL_API_KEY="${api_key}"

healthy() {
  curl --fail --silent --max-time 5 \
    -H "Authorization: Bearer ${api_key}" \
    http://127.0.0.1:8004/health >/dev/null 2>&1
}

if [[ -f "${PID_FILE}" ]]; then
  pid="$(<"${PID_FILE}")"
  if kill -0 "${pid}" 2>/dev/null && healthy; then
    echo "MPS accelerator is already healthy on http://127.0.0.1:8004."
    exit 0
  fi
  rm -f "${PID_FILE}"
fi
if healthy; then
  # Refusing is right -- an accelerator this launcher did not start may be
  # serving older code. Refusing without saying how to recover is not: this
  # aborts prepare_and_start_local_app.sh under `set -e`, so RAG is never
  # rebuilt, and the operator is left with a stack that looks started and
  # answers nothing.
  echo "Port 8004 is serving an accelerator this launcher did not start." >&2
  echo "It answers with the credential in ${KEY_FILE}, so it is almost" >&2
  echo "certainly an orphan from an earlier run. Stop it and start again:" >&2
  echo "  lsof -ti tcp:8004 | xargs kill" >&2
  echo "  ./scripts/prepare_and_start_local_app.sh" >&2
  exit 1
fi

nohup /bin/bash "${SCRIPT_DIRECTORY}/run_accelerator_macos.sh" \
  >>"${LOG_FILE}" 2>&1 &
accelerator_pid="$!"
printf '%s\n' "${accelerator_pid}" >"${PID_FILE}"

for _ in {1..120}; do
  if healthy; then
    echo "MPS accelerator started on http://127.0.0.1:8004 (PID ${accelerator_pid})."
    exit 0
  fi
  if ! kill -0 "${accelerator_pid}" 2>/dev/null; then
    break
  fi
  sleep 1
done

echo "MPS accelerator failed. Review ${LOG_FILE}." >&2
kill "${accelerator_pid}" 2>/dev/null || true
rm -f "${PID_FILE}"
exit 1
