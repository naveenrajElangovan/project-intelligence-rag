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

The answer contract is fail-closed. Every factual request returns one of
`ANSWERED`, `NEEDS_CLARIFICATION`, `INSUFFICIENT_EVIDENCE`, `SOURCE_CONFLICT`,
or `ACCESS_DENIED`. `ANSWERED` is emitted only after the atomic-claim gate checks
citations, selected source scope, access, freshness, conflicts, and requested
coverage. Existing consumers can keep reading `answer` and `sources`; the API
also returns `citations`, `resolvedIntent`, `resolvedEntities`, `coverage`, and
`failureReason`.

Ingested source records should carry `canonical_entity_id`, `parent_id`,
`source_version`, `observed_at`, `authority`, and `access_policy_id`. Structured
facts also carry `field_path` and `normalized_value`. Searchable chunks retain
the parent ID and version so a match can be reconstructed into the complete,
authorized parent record before answering.

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
answer text is withheld until claim, coverage, conflict, freshness, scope, and permission checks
finish. The service then emits one `answer_snapshot` followed by the authoritative `complete`
event. It never sends provisional factual tokens, because content that is individually plausible
can still fail the final whole-answer gate.

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

The complete service boundaries are documented in the
[backend architecture](../project-intelligence-backend/docs/CURRENT_ARCHITECTURE.md),
[ingestion architecture](../project-intelligence-ingestion/docs/CURRENT_ARCHITECTURE.md),
[Atlassian integration architecture](../project-intelligence-atlassian/docs/ARCHITECTURE.md), and
[observability architecture](../project-intelligence-observability/docs/ARCHITECTURE.md).
Provider selection, exact Jira aggregates, LiteLLM model routing, operational controls, and live
verification are documented in [provider routing and Jira aggregates](docs/PROVIDER_ROUTING_AND_JIRA_AGGREGATES.md).
The company-facing privacy, LLM data-use, threat-model, and production approval guidance is in the
[enterprise security architecture](../project-intelligence-backend/PROJECT_INTELLIGENCE_SECURITY_ARCHITECTURE.md).
Backend authorization and ingestion procedures live in their respective repositories.

Executable production-component labs are in [labs/README.md](labs/README.md). The evidence-derived
live DEMO acceptance gate is `evaluation/t2_live_acceptance.json`. The default local evaluation
also loads the 80 source-bound bilingual cases in `evaluation/bilingual_gold_suites.jsonl` and
reports every metric by query language. Retired cases remain recorded with their reasons but are
excluded from scoring; the current active retrieval lane contains 284 cases.
`evaluation/run_retrieval_eval.py` has two deliberately separate lanes: the default
retrieval gate reports recall, nDCG, and gold survival; `--generate N` (30–40) runs the full
generation, citation-validation, and grounding workflow and is the only lane that reports
grounding acceptance, citation precision, refusal precision, and refusal-reason accuracy. The
generation lane is intended for nightly use, not per-commit CI.
Before retrieval starts, the runner requires at least 95% of answerable gold predicates to resolve
against the live namespace. Missing or stale source coverage is a hard failure with case IDs rather
than a silent drop from recall and nDCG.

## OpenInference, Phoenix, and Ragas

Set `PI_RAG_OPENINFERENCE_ENABLED=true` to instrument LangGraph/LangChain with
OpenInference and send OTLP traces to the configured collector. Inputs,
outputs, message text, prompts, tool schemas, and embedding content are hidden
by default. Phoenix is the sole owner of RAG traces and evaluation results.

For controlled offline quality evaluation, install the optional evaluator and
run it against a curated JSONL file containing `user_input`, `response`,
`retrieved_contexts`, and `reference`:

```bash
.venv/bin/pip install -r requirements-eval.txt
.venv/bin/python -m evaluation.run_ragas_eval \
  --input evaluation/ragas_dataset.example.jsonl
```

The evaluator uses the local OpenAI-compatible Ollama endpoint by default,
writes `evaluation/ragas-results.json`, attaches aggregate scores to its
evaluation span in Phoenix, and traces evaluator model calls through
OpenInference. Faithfulness, answer relevancy, and answer correctness are the
standard answer-generation metrics. Add `--include-factual-correctness` for the
slower optional diagnostic; on the bundled local model this can take several
minutes per sample.
Use a reviewed internal dataset rather than production conversations unless
your privacy policy explicitly permits evaluation of that content.

Phoenix is the sole owner of RAG quality history. A completed quality run has
`rag.quality.retrieval` and `rag.quality.answer_generation` child spans. Each
contains overall, English, Spanish, signed language-gap, and absolute-gap annotations. Only scores,
counts, version identifiers, and model names are published; evaluation content
stays in the local gitignored run directory. Prometheus and Grafana remain for
operational health (latency, traffic, capacity, dependency failures, retries,
and tokens) and must not duplicate these quality scores.

`scripts/run_quality_monitor.sh` runs both sections and publishes them only
after both finish. Set `PI_RAG_RAGAS_REFERENCES` to a reviewed bilingual
reference-answer JSONL file and `PI_RAG_QUALITY_PROJECT_ID` to the authorized
project. Each reference row contains `case_id`, both language fields,
`question_sha256`, `reference`, `reference_status: "reviewed"`, and one shared
`dataset_version`; the monitor joins these
to the source-bound cases and generates fresh answers and exact contexts through
the production workflow. Generate the 60-row review worksheet with
`.venv/bin/python -m evaluation.build_bilingual_reference_template --out <path>`;
an owner must fill each reference from its approved gold source and change its
status only after review. The supplied
`scripts/com.project-intelligence.rag-quality.plist` schedules it daily at
02:00 local time on the validated macOS evaluation host. Replace the reference
path placeholder in that file, then copy and load it explicitly after the
dataset and local services are ready. The plist is intentionally not installed
until all bilingual references have been reviewed. The same script is the pre-release
quality command.
