# Project Intelligence RAG

This service owns authorized bilingual Chroma retrieval, multilingual reranking, and grounded
LLM answers. LangChain owns adapters/prompts/structured output; LangGraph owns deterministic flow.

Flow:

1. The client calls the backend with an Entra access token.
2. The backend validates identity and project access.
3. The backend calls this private service with the project ID and authorized policy IDs.
4. It validates the allowlisted host and project namespace, then applies exact project filters.
5. Package-A planning uses the minimum safe query set, then deduplicates authorized candidates.
6. Corpus vocabulary, exact feature affinity, metadata-facet fusion, and local
   `bge-reranker-v2-m3` select evidence; ingestion-marked low-information chunks are excluded.
7. Evidence and answer completeness allow one targeted retrieval repair; citations and claims are
   verified before release.
8. Missing evidence or a dependency failure never falls back to model knowledge.

The service must not be public. Development may omit `PI_RAG_INTERNAL_API_KEY` only when the
service is kept on the local machine/private Compose network. Production requires the key; keep
it in Key Vault and expose the RAG service only through private ingress.
Production also requires explicit trusted hosts, HTTPS, and disabled API documentation. The
approved default is fully local Ollama generation and local BGE reranking; managed OpenAI routes
remain explicit alternatives and are never automatic fallbacks.

Local operation uses the stable `pi-qwen3.5:2026-08` Ollama alias for planning, recovery-query
generation, and answering, plus a pinned offline `bge-reranker-v2-m3` for reranking and grounding
verification. Concurrency and context are
bounded for the validated M5 Max/64 GB laptop profile. The mobile client never supplies a model
name. No matching authorized evidence skips answer generation entirely.

`POST /v1/answer/stream` returns NDJSON. Status events never contain project content. With
`PI_RAG_INCREMENTAL_VERIFIED_STREAMING_ENABLED=true`, prose tokens are emitted immediately as
`answer_delta` events with `verification: "pending"`. Each citation-complete sentence is then
checked independently and followed by either `answer_sentence_verified` or
`answer_sentence_rejected`; the final `complete` event is authoritative and contains the verified
answer plus structured citations and missing-information metadata. Deterministic transforms,
refusals, and other paths that only have finished text emit one `answer_snapshot`; clients render
that as a complete message and do not pretend it was token-streamed. The default remains off so
incremental provisional rendering can be disabled without a deployment.

Run locally:

```bash
cp .env.example .env
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8003
```

On the validated Apple Silicon laptop, use `./scripts/start_local_macos.sh` and
`./scripts/stop_local_macos.sh`. The launcher proves MPS is available and refuses CPU fallback.

The implemented design, diagrams, security boundaries, code map, deployment topology, and failure
behavior are documented in the single [current RAG architecture](docs/CURRENT_ARCHITECTURE.md).
The company-facing privacy, LLM data-use, threat-model, and production approval guidance is in the
[enterprise security architecture](../project-intelligence-backend/PROJECT_INTELLIGENCE_SECURITY_ARCHITECTURE.md).
Backend authorization and ingestion procedures live in their respective repositories.

Executable production-component labs are in [labs/README.md](labs/README.md). The evidence-derived
live DEMO acceptance gate is `evaluation/t2_live_acceptance.json`; the older 80-case file is a
fixture scaffold and must not be treated as a release gate until its gold sources are curated.
`evaluation/run_retrieval_eval.py` has two deliberately separate lanes: the default 318-case
retrieval gate reports recall, nDCG, and gold survival; `--generate N` (30–40) runs the full
generation, citation-validation, and grounding workflow and is the only lane that reports
grounding acceptance, citation precision, refusal precision, and refusal-reason accuracy. The
generation lane is intended for nightly use, not per-commit CI.
