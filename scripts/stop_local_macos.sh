#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIRECTORY="$(cd "${SCRIPT_DIRECTORY}/.." && pwd)"
PID_FILE="${PROJECT_DIRECTORY}/.run/rag.pid"

# The application reads .env; these scripts read the shell environment. Left
# unreconciled they validate and release a different model from the one actually
# in use — the launcher checked a model the app never loads, and the stop script
# released it. Resolution order matches the backend launcher: shell, then .env,
# then default.
read_env_value() {
  local requested_key="$1" line key
  local env_file="${PROJECT_DIRECTORY}/.env"
  [[ -f "${env_file}" ]] || return 0
  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ "${line}" == \#* ]] && continue
    key="${line%%=*}"
    if [[ "${key}" == "${requested_key}" ]]; then
      line="${line#*=}"
      printf '%s' "${line%$'\r'}"
      return 0
    fi
  done < "${env_file}"
}

resolve_setting() {
  local key="$1" fallback="$2" value
  value="${!key:-}"
  [[ -n "${value}" ]] || value="$(read_env_value "${key}")"
  printf '%s' "${value:-${fallback}}"
}

PORT="$(resolve_setting PI_RAG_LOCAL_PORT 8003)"
GENERATOR_MODEL="$(resolve_setting PI_RAG_OLLAMA_MODEL qwen3.5:latest)"
PLANNER_MODEL="$(resolve_setting PI_RAG_OLLAMA_PLANNER_MODEL "${GENERATOR_MODEL}")"

# The recorded pid is a hint, not the authority. A pid file can outlive its
# process, or name a process that was replaced; trusting it alone let this script
# report success while the service kept serving, and then delete the only record
# of what was running. What actually matters is whether the port is still held.
listeners() {
  lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null || true
}

targets=""
if [[ -f "${PID_FILE}" ]]; then
  recorded="$(tr -cd '0-9' <"${PID_FILE}")"
  if [[ -n "${recorded}" ]] && kill -0 "${recorded}" 2>/dev/null; then
    targets="${recorded}"
  fi
fi
for pid in $(listeners); do
  case " ${targets} " in
    *" ${pid} "*) ;;
    *) targets="${targets} ${pid}" ;;
  esac
done
targets="$(echo "${targets}" | xargs || true)"

if [[ -z "${targets}" ]]; then
  echo "No local RAG process is running on port ${PORT}."
else
  for pid in ${targets}; do
    kill "${pid}" 2>/dev/null || true
  done
  # Give uvicorn a chance to shut down cleanly before insisting.
  for _ in {1..20}; do
    [[ -z "$(listeners)" ]] && break
    sleep 0.5
  done
  if [[ -n "$(listeners)" ]]; then
    for pid in $(listeners); do
      kill -9 "${pid}" 2>/dev/null || true
    done
    sleep 1
  fi
  if [[ -n "$(listeners)" ]]; then
    echo "Port ${PORT} is still held after SIGKILL by: $(listeners | xargs)" >&2
    echo "The pid file was left in place so the state stays inspectable." >&2
    exit 1
  fi
  echo "Stopped local RAG (pid(s) ${targets})."
fi

# Only remove the record once the port is demonstrably free, so a failed stop
# never destroys the evidence of what was running.
rm -f "${PID_FILE}"

for model in $(printf '%s\n' "${GENERATOR_MODEL}" "${PLANNER_MODEL}" | sort -u); do
  if ollama stop "${model}" >/dev/null 2>&1; then
    echo "Released ${model} from memory."
  fi
done
