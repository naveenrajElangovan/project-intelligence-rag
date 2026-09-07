#!/bin/zsh
set -euo pipefail

umask 077
script_dir=${0:A:h}
repo_dir=${script_dir:h}
python_bin=${repo_dir}/.venv/bin/python
project_id=${PI_RAG_QUALITY_PROJECT_ID:-T2.0}
ragas_references=${PI_RAG_RAGAS_REFERENCES:-}
dataset_version=${PI_RAG_DATASET_VERSION:-1}
output_root=${PI_RAG_QUALITY_OUTPUT_DIR:-${repo_dir}/.quality-runs}
retained_runs=${PI_RAG_QUALITY_RETAIN_RUNS:-14}
max_runtime_seconds=${PI_RAG_QUALITY_MAX_RUNTIME_SECONDS:-21600}
phoenix_url=${PI_RAG_PHOENIX_URL:-http://127.0.0.1:6006}
# Quality spans always traverse the collector so its privacy scrubber remains mandatory.
otlp_endpoint=${PI_RAG_OPENINFERENCE_OTLP_ENDPOINT:-http://127.0.0.1:4318/v1/traces}
ollama_url=${PI_RAG_OLLAMA_BASE_URL:-http://127.0.0.1:11434}
rag_url=${PI_RAG_QUALITY_RAG_URL:-http://127.0.0.1:8003}
judge_model=${PI_RAG_RAGAS_MODEL:-pi-qwen3.5:2026-08}
lock_dir=${output_root}/.running
run_id=""
commit_sha="unknown"
stage="startup"
lock_owned=0

if [[ ! -x ${python_bin} ]]; then
  print -u2 "Missing evaluation environment: ${python_bin}"
  exit 2
fi

mkdir -p ${output_root} ${output_root}/logs
chmod 700 ${output_root} ${output_root}/logs

take_lock() {
  if mkdir ${lock_dir} 2>/dev/null; then
    lock_owned=1
    print "$$ $(date +%s)" > ${lock_dir}/owner
    return 0
  fi
  local owner_pid="" owner_started=0 now=$(date +%s)
  if [[ -r ${lock_dir}/owner ]]; then
    read owner_pid owner_started < ${lock_dir}/owner || true
  fi
  if [[ -n ${owner_pid} ]] && kill -0 ${owner_pid} 2>/dev/null && \
      (( now - owner_started <= max_runtime_seconds )); then
    return 1
  fi
  print -u2 "Recovering stale RAG quality lock (pid=${owner_pid:-unknown})."
  rm -f -- ${lock_dir}/owner
  rmdir ${lock_dir} 2>/dev/null || return 1
  mkdir ${lock_dir}
  lock_owned=1
  print "$$ ${now}" > ${lock_dir}/owner
}

if ! take_lock; then
  print -u2 "A RAG quality evaluation is already running."
  exit 3
fi

run_id=$(date -u +%Y%m%dT%H%M%SZ)
commit_sha=$(git -C ${repo_dir} rev-parse HEAD)
if [[ -n $(git -C ${repo_dir} status --porcelain) ]]; then
  commit_sha=${commit_sha}-dirty
fi

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  if (( exit_code != 0 )) && [[ -n ${run_id} && ${stage} != "completed" ]]; then
    ${python_bin} -m evaluation.publish_quality_run \
      --status failed \
      --failed-stage ${stage} \
      --project-id ${project_id} \
      --run-id ${run_id} \
      --dataset-version ${dataset_version} \
      --commit-sha ${commit_sha} \
      --judge-model ${judge_model} \
      --phoenix-url ${phoenix_url} \
      --otlp-endpoint ${otlp_endpoint} >/dev/null 2>&1 || true
  fi
  if (( lock_owned )); then
    rm -f -- ${lock_dir}/owner
    rmdir ${lock_dir} 2>/dev/null || true
  fi
  exit ${exit_code}
}
trap cleanup EXIT
trap 'exit 130' INT TERM

if [[ -z ${ragas_references} || ! -f ${ragas_references} ]]; then
  stage="references_preflight"
  print -u2 "PI_RAG_RAGAS_REFERENCES must name a reviewed bilingual reference JSONL file."
  exit 2
fi

stage="phoenix_preflight"
if ! ${python_bin} -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1].rstrip("/") + "/healthz", timeout=5)' ${phoenix_url} 2>/dev/null; then
  print -u2 "Phoenix is unreachable at ${phoenix_url}."
  exit 4
fi

stage="ollama_preflight"
if ! ${python_bin} -c 'import json,sys,urllib.request; payload=json.load(urllib.request.urlopen(sys.argv[1].rstrip("/") + "/api/tags",timeout=5)); names={m.get("name") for m in payload.get("models",[])}; raise SystemExit(0 if sys.argv[2] in names else 1)' ${ollama_url} ${judge_model} 2>/dev/null; then
  print -u2 "Ollama is unreachable or judge model ${judge_model} is not installed."
  exit 5
fi

stage="rag_health_preflight"
if ! ${python_bin} -c 'import sys,urllib.request; urllib.request.urlopen(sys.argv[1].rstrip("/") + "/health",timeout=5)' ${rag_url} 2>/dev/null; then
  print -u2 "RAG health check failed at ${rag_url}/health."
  exit 6
fi

run_dir=${output_root}/${run_id}
mkdir -m 700 ${run_dir}
previous_args=()
if [[ -e ${output_root}/latest-successful/retrieval.json && \
      -e ${output_root}/latest-successful/answer-generation.json ]]; then
  previous_args=(
    --previous-retrieval ${output_root}/latest-successful/retrieval.json
    --previous-answer-generation ${output_root}/latest-successful/answer-generation.json
  )
fi

stage="retrieval_and_generation"
${python_bin} -m evaluation.run_retrieval_eval \
  --project-id ${project_id} \
  --out ${run_dir}/retrieval.jsonl \
  --phoenix-url "" \
  --dataset-version ${dataset_version} \
  --commit-sha ${commit_sha} \
  --ragas-references ${ragas_references} \
  --ragas-out ${run_dir}/ragas-input.jsonl

stage="ragas"
${python_bin} -m evaluation.run_ragas_eval \
  --input ${run_dir}/ragas-input.jsonl \
  --output ${run_dir}/answer-generation.json \
  --model ${judge_model} \
  --phoenix-url "" \
  --project-id ${project_id} \
  --quality-run-id ${run_id} \
  --dataset-version ${dataset_version} \
  --commit-sha ${commit_sha} \
  --require-bilingual-reviewed

stage="phoenix_publish"
${python_bin} -m evaluation.publish_quality_run \
  --retrieval ${run_dir}/retrieval.json \
  --answer-generation ${run_dir}/answer-generation.json \
  --generation-diagnostics ${run_dir}/ragas-input.generation.json \
  --project-id ${project_id} \
  --run-id ${run_id} \
  --dataset-version ${dataset_version} \
  --commit-sha ${commit_sha} \
  --judge-model ${judge_model} \
  --phoenix-url ${phoenix_url} \
  --otlp-endpoint ${otlp_endpoint} \
  ${previous_args[@]}

ln -sfn ${run_dir} ${output_root}/latest-successful
stage="retention"
run_dirs=(${(f)"$(find ${output_root} -mindepth 1 -maxdepth 1 -type d -name '20??????T??????Z' -print | sort -r)"})
if (( ${#run_dirs} > retained_runs )); then
  for old_run in ${run_dirs[$((retained_runs + 1)),-1]}; do
    rm -rf -- ${old_run}
  done
fi
stage="completed"
