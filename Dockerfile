FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANGCHAIN_TRACING_V2=false \
    LANGSMITH_TRACING=false

WORKDIR /app
COPY requirements.txt .
# torch is installed first, from PyTorch's CPU-only index. On Linux the default
# PyPI wheel hard-depends on nvidia-cudnn-cu13, nvidia-cusparselt-cu13,
# nvidia-nccl-cu13, nvidia-nvshmem-cu13 and triton -- about 1.1 GB of compressed
# wheels, roughly 2 GB installed -- and every byte of it is dead weight on a
# server with no GPU. The reranker and the query embedder both run on CPU there,
# so nothing is given up. Revert this line if the service is ever moved to a GPU
# instance.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.11.0 \
 && pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY scripts ./scripts
RUN python -m scripts.generate_sbom /opt/project-intelligence-rag.cdx.json
RUN useradd --create-home --uid 10001 appuser
USER appuser
EXPOSE 8002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", "--proxy-headers"]
