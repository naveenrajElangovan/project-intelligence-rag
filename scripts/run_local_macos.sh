#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIRECTORY="$(cd "${SCRIPT_DIRECTORY}/.." && pwd)"
MODEL_DIRECTORY="${PROJECT_DIRECTORY}/.models/bge-reranker-v2-m3"
EMBEDDER_DIRECTORY="${PROJECT_DIRECTORY}/.models/multilingual-e5-large"

cd "${PROJECT_DIRECTORY}"
export PI_RAG_OLLAMA_BASE_URL=http://127.0.0.1:11434
export PI_RAG_LOCAL_INFERENCE_ENABLED=true
export PI_RAG_LOCAL_RERANK_DEVICE=mps
export PI_RAG_LOCAL_MODELS_PATH="${MODEL_DIRECTORY}"
# Exported so a direct foreground run behaves identically to the guarded
# launcher, rather than depending on .env being present and correct.
export PI_RAG_LOCAL_EMBEDDING_PATH="${PI_RAG_LOCAL_EMBEDDING_PATH:-${EMBEDDER_DIRECTORY}}"
export PI_RAG_LOCAL_EMBEDDING_DEVICE="${PI_RAG_LOCAL_EMBEDDING_DEVICE:-mps}"
export PI_RAG_CHROMA_HOST="${PI_RAG_CHROMA_HOST:-127.0.0.1}"
export PI_RAG_ALLOWED_HOSTS=localhost,127.0.0.1,host.docker.internal,rag,testserver
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8003
