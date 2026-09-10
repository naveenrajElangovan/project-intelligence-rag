# Phoenix AI quality control plane

Phoenix is an offline quality and content system. Grafana remains the source for
infrastructure, capacity, and alerting. A request never calls Phoenix or an
evaluator synchronously.

## Security boundary

Deploy one Phoenix/collector stack per project or department boundary. Set
`PI_PHOENIX_BOUNDARY` to that boundary; the collector drops every span without
the exact matching server-generated `auth.boundary`. Browser access uses a
boundary-specific Entra group. API traffic uses a Phoenix bearer key. Phoenix
trace retention is 30 days; dataset, prompt, and experiment artifacts are not
trace-retention data.

`metadata_only` is the RAG default. `full_authorized` adds the redacted question,
final answer, citations, and only evidence selected for the model. Automatic
LangChain content capture remains hidden because retriever outputs can include
discarded candidates. Candidate identifiers and scores are recorded without
candidate bodies. Access-policy IDs, raw identities, credentials, cookies,
tokens, and embedding vectors are never recorded.

## Datasets

Import a reviewed immutable suite into the Phoenix instance for its boundary:

```bash
PI_RAG_PHOENIX_API_KEY=... .venv/bin/python -m evaluation.phoenix_assets \
  evaluation/bilingual_gold_suites.jsonl \
  --boundary project:T2.0 \
  --dataset-version 1
```

The importer rejects mixed projects and duplicate case IDs. It writes stable
case IDs and content hashes. Re-running an identical import is idempotent; a
same-name/different-content import fails instead of mutating a reviewed version.
Production failures belong in a separately named rolling dataset and must be
redacted and reviewed before promotion into a gold suite.

## Prompt synchronization

Runtime prompts remain bundled in Git and releases pin `PI_RAG_PROMPT_VERSION`
to the Git SHA. Phoenix is never read during an answer request. Publish the exact
literal templates from the released source for comparison:

```bash
PI_RAG_PHOENIX_API_KEY=... .venv/bin/python -m evaluation.sync_prompts \
  --tag candidate --model-name qwen3.5:latest
```

Each prompt version carries its Git SHA, schema version, owner, release tag, and
content hash.

## Experiments and evaluators

`evaluation.phoenix_assets.publish_experiment` creates a Phoenix experiment and
publishes every example output, trace ID, deterministic score, and semantic
score at row level. `evaluation.deterministic_evaluators.evaluate_case` runs the
fast suite before any model judge: authorization leakage, citation validity,
language, completeness, refusal typing, source coverage, latency, dependency
classification, and refusal appropriateness. Existing Ragas evaluation supplies
groundedness, relevance, completeness, and reviewed-reference correctness.

The authenticated backend exposes:

- `POST /v1/evaluations` — returns `202` and a durable run ID;
- `GET /v1/evaluations/{runId}` — returns status, Phoenix reference, aggregate
  scores, and typed failures;
- `GET /v1/evaluator-suites/{version}` — returns the immutable suite definition.

Submission requires Entra project membership. Candidate input is a bounded
allowlist of prompt/model/retrieval controls; endpoints, API keys, and Phoenix
credentials cannot be supplied by callers. Jobs go to Azure Service Bus through
managed identity and run state is stored in Azure SQL.

## Release order

Back up the Phoenix volume, configure unique secrets and Entra app/group values,
deploy one stack per boundary, create a scoped system API key, import datasets,
synchronize prompts, enable staging `full_authorized` traces, run the baseline
experiment, deploy the evaluation workers, and only then enable sampled
production content traces. Never reuse Phoenix volumes, signing secrets, API
keys, or Entra allowed groups between authorization boundaries.
