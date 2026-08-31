#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIRECTORY="$(cd "${SCRIPT_DIRECTORY}/.." && pwd)"
MODEL_DIRECTORY="${PROJECT_DIRECTORY}/.models/bge-reranker-v2-m3"
EMBEDDER_DIRECTORY="${PROJECT_DIRECTORY}/.models/multilingual-e5-large"
RUNTIME_DIRECTORY="${PROJECT_DIRECTORY}/.run"
PID_FILE="${RUNTIME_DIRECTORY}/rag.pid"
LOG_FILE="${RUNTIME_DIRECTORY}/rag.log"


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

GENERATOR_MODEL="$(resolve_setting PI_RAG_OLLAMA_MODEL qwen3.5:latest)"
PLANNER_MODEL="$(resolve_setting PI_RAG_OLLAMA_PLANNER_MODEL "${GENERATOR_MODEL}")"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "This launcher is only for Apple Silicon macOS." >&2
  exit 1
fi
if [[ ! -x "${PROJECT_DIRECTORY}/.venv/bin/python" ]]; then
  echo "Create the RAG virtual environment and install requirements first." >&2
  exit 1
fi
if [[ ! -d "${MODEL_DIRECTORY}" ]]; then
  echo "Pinned BGE model is missing. Run scripts/download_local_reranker.py first." >&2
  exit 1
fi
if [[ ! -d "${EMBEDDER_DIRECTORY}" ]]; then
  echo "Pinned E5 embedder is missing. Run:" >&2
  echo "  scripts/download_local_embedder.py .models/multilingual-e5-large" >&2
  echo "Local embedding is required for Chroma retrieval." >&2
  exit 1
fi
for model in $(printf '%s\n' "${GENERATOR_MODEL}" "${PLANNER_MODEL}" | sort -u); do
  if ! ollama show "${model}" >/dev/null 2>&1; then
    echo "Ollama model ${model} is unavailable." >&2
    exit 1
  fi
done
if ! "${PROJECT_DIRECTORY}/.venv/bin/python" -c \
  'import torch,sys; sys.exit(0 if torch.backends.mps.is_available() else 1)'; then
  echo "Apple MPS is unavailable; refusing CPU fallback." >&2
  exit 1
fi

# Size the context window from installed memory. Qwen3.5 reports a 262,144-token
# native context and uses hybrid attention, so many layers keep no KV cache and a
# large window costs far less than it would on a standard transformer. An explicit
# PI_RAG_OLLAMA_CONTEXT_TOKENS always wins.
if [[ -z "${PI_RAG_OLLAMA_CONTEXT_TOKENS:-}" ]]; then
  MEMORY_BYTES="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
  MEMORY_GIB=$(( MEMORY_BYTES / 1073741824 ))
  if (( MEMORY_GIB >= 128 )); then
    CONTEXT_TOKENS=131072
  elif (( MEMORY_GIB >= 64 )); then
    CONTEXT_TOKENS=65536
  elif (( MEMORY_GIB >= 32 )); then
    CONTEXT_TOKENS=32768
  elif (( MEMORY_GIB >= 16 )); then
    CONTEXT_TOKENS=16384
  else
    # Below 16 GiB the default 2048-token output reservation leaves too little
    # room for evidence to satisfy the configuration validator, so the answer
    # budget is trimmed rather than the service refusing to start.
    CONTEXT_TOKENS=12288
    if [[ -z "${PI_RAG_OLLAMA_MAX_OUTPUT_TOKENS:-}" ]]; then
      export PI_RAG_OLLAMA_MAX_OUTPUT_TOKENS=1024
      echo "Under 16 GiB: answer length reduced to 1024 tokens to fit the window."
    fi
  fi
  export PI_RAG_OLLAMA_CONTEXT_TOKENS="${CONTEXT_TOKENS}"
  echo "Detected ${MEMORY_GIB} GiB; context window set to ${CONTEXT_TOKENS} tokens."
fi

# Keep the evidence budget inside the window the configuration validator enforces,
# so a small machine degrades to less evidence instead of refusing to start.
if [[ -z "${PI_RAG_MAX_EVIDENCE_TOKENS:-}" ]]; then
  RESERVED=$(( ${PI_RAG_OLLAMA_MAX_OUTPUT_TOKENS:-2048} + 2048 + 2000 + 1000 ))
  # The configuration validator refuses to start when evidence plus the reserved
  # parts exceed the window, so the budget is clamped to what actually fits
  # before any floor is applied. A floor above the ceiling was a real defect: it
  # made the service unstartable on a small machine.
  CEILING=$(( PI_RAG_OLLAMA_CONTEXT_TOKENS - RESERVED - 512 ))
  BUDGET=$(( PI_RAG_OLLAMA_CONTEXT_TOKENS - RESERVED - 2048 ))
  if (( BUDGET > 16000 )); then
    BUDGET=16000
  fi
  if (( BUDGET > CEILING )); then
    BUDGET="${CEILING}"
  fi
  if (( BUDGET < 1000 )); then
    echo "This machine cannot fit the prompt: a ${PI_RAG_OLLAMA_CONTEXT_TOKENS}-token" >&2
    echo "window leaves only ${BUDGET} tokens for evidence after ${RESERVED} reserved." >&2
    echo "Lower PI_RAG_OLLAMA_MAX_OUTPUT_TOKENS or raise PI_RAG_OLLAMA_CONTEXT_TOKENS." >&2
    exit 1
  fi
  export PI_RAG_MAX_EVIDENCE_TOKENS="${BUDGET}"
  echo "Evidence budget set to ${BUDGET} tokens."
fi

if curl --fail --silent http://127.0.0.1:8003/health >/dev/null 2>&1; then
  # Health says nothing about *which* code is answering. This launcher is
  # idempotent by design, so after an edit it would report success while the
  # running process still served the previous revision — the failure mode is a
  # change that appears to have had no effect. Compare the sources against the
  # moment the process started and refuse rather than mislead.
  if [[ ! -f "${PID_FILE}" ]]; then
    # Something answers on 8003 but this launcher has no record of starting it.
    # That is an orphan from an earlier run, and it is the case most likely to be
    # serving stale code, so it must not fall through to "already healthy".
    echo "Something is serving http://127.0.0.1:8003 but ${PID_FILE} is absent," >&2
    echo "so this launcher did not start it and cannot tell which code it runs." >&2
    echo "Stop it and start again:" >&2
    echo "  ./scripts/stop_local_macos.sh && ./scripts/start_local_macos.sh" >&2
    exit 1
  fi
  if [[ -f "${PID_FILE}" ]]; then
    # Absolute paths on purpose. The `cd` into the project happens further down,
    # so a relative `find` here would inspect whatever directory the caller was
    # in — the ingestion repo, when this runs via run_unattended_ingestion.sh —
    # and compare the wrong tree against this service's start time.
    # Only what the running process actually loaded. `scripts/` shapes the next
    # launch, not the current one — this launcher is executing the new copy right
    # now — and editing requirements.txt does not change the installed venv. A
    # check that fires on those trains you to set the override, which costs more
    # than the check is worth.
    STALE=""
    for candidate in app .env; do
      target="${PROJECT_DIRECTORY}/${candidate}"
      [[ -e "${target}" ]] || continue
      if [[ -n "$(find "${target}" -newer "${PID_FILE}" -print -quit 2>/dev/null || true)" ]]; then
        STALE="${candidate}"
        break
      fi
    done
    if [[ -n "${STALE}" && "${PI_DEV_ALLOW_STALE_RAG:-false}" != "true" ]]; then
      # Refusing here only moved the work to the operator: the launcher already
      # knows the process is stale and knows exactly which two commands fix it.
      # It stops the old process and re-executes itself, so the pre-flight
      # checks and memory sizing all run again against the new code. The
      # re-entry guard turns a restart that does not clear the condition into a
      # single hard failure instead of a loop.
      if [[ "${PI_DEV_RAG_RESTARTED:-false}" == "true" ]]; then
        echo "RAG still reports stale code (${STALE}) after a restart." >&2
        echo "Something is rewriting app/ or .env while it starts." >&2
        exit 1
      fi
      echo "RAG is running older code than disk (changed: ${STALE}). Restarting it."
      "${SCRIPT_DIRECTORY}/stop_local_macos.sh" || true
      PI_DEV_RAG_RESTARTED=true exec "${BASH_SOURCE[0]}" "$@"
    fi
  fi
  echo "RAG is already healthy at http://127.0.0.1:8003."
  exit 0
fi

mkdir -p "${RUNTIME_DIRECTORY}"
cd "${PROJECT_DIRECTORY}"
nohup ./scripts/run_local_macos.sh >>"${LOG_FILE}" 2>&1 &
RAG_PID="$!"
echo "${RAG_PID}" >"${PID_FILE}"

for _ in {1..30}; do
  if curl --fail --silent http://127.0.0.1:8003/health >/dev/null 2>&1; then
    echo "Local RAG started on http://127.0.0.1:8003 (PID ${RAG_PID})."
    exit 0
  fi
  if ! kill -0 "${RAG_PID}" 2>/dev/null; then
    break
  fi
  sleep 1
done

echo "RAG failed readiness. Review ${LOG_FILE}." >&2
kill "${RAG_PID}" 2>/dev/null || true
exit 1
