# Project Intelligence RAG — quality status

Last verified: 2026-09-18. This is the sole current quality summary. All values
below are measured results from retained artifacts or direct command execution, not
projections. The remediation and cross-repository consolidation are closed; new
work starts from this file and `docs/CURRENT_ARCHITECTURE.md`.

The suite-wide dependency rule is the canonical
[exact-pin policy](DEPENDENCY_POLICY.md); this repository's `pyproject.toml` is
its sole dependency declaration.

## Release conclusion

The Store gates pass with material margin, the active Developer corpus has complete
EventType coverage, Phase 4 resolves the serving route correctly, exact generation
is reproducible, and live sync/stream behavior is bilingual and fail-closed. The
full local stack was rebuilt from source and is healthy.

One non-release-blocking evaluation limitation remains: the raw Developer retrieval
suite is 310 English cases and 30 Spanish cases and does not use the production
translation bridge. Its language hit-rate gap is reported below, not hidden. The
live bilingual generation path does not exhibit that failure.

## Single vector schema invariant

Schema version **3** is the only accepted vector schema throughout all five
applications. There is no active v2/v4 compatibility or rollback route.

| Repository | Enforcement |
|---|---|
| `project-intelligence-rag` | Settings accepts exactly `3`; routing and requests use v3 |
| `project-intelligence-ingestion` | Settings and persisted routes accept exactly `3` |
| `project-intelligence-backend` | API/config, staging manifests, and persisted routes accept exactly `3`; invalid versions fail closed |
| `project-intelligence-atlassian` | Does not select/write schemas; ingestion owns the v3 write contract |
| `project-intelligence-mobile` | Does not select a schema; backend owns the v3 request contract |

Examples, templates, manifests, corpus configuration, tests, and current
architecture documents use v3. Repository-wide older schema numbers occur only in
negative rejection tests or unrelated source/evaluation file-format schemas.

## Quality gates

### Store

| Metric | Baseline | Final | Gate | Result |
|---|---:|---:|---:|---|
| candidate hit@25 | 100.0000% | 100.0000% | diagnostic | PASS |
| hit@16 | 90.1685% | 100.0000% | >=75% | PASS |
| section hit@16 | 90.1685% | 100.0000% | >=75% | PASS |
| recall@25 | 85.9660% | 87.7334% | diagnostic | PASS |
| grounding acceptance | 90.1685% | 99.4382% | >=85% | PASS |
| citation precision | 100.0000% | 100.0000% | 100% | PASS |
| refusal precision | 25.5319% | 85.7143% | >=80% | PASS |
| out-of-scope answer rate | 0.0000% | 0.0000% | <=5% | PASS |
| project/department leakage | 0 / 0 | 0 / 0 | 0 / 0 | PASS |

The latest post-fix Store retrieval suite contains 356 cases; generation contains
368. English/Spanish recall differs by 0.258 points. Fresh generation measured
grounding at 98.8764%/100% and refusal precision at 75%/100% for English/Spanish,
respectively; aggregate grounding/refusal remain above their declared gates and
all languages have 100% citation precision and zero out-of-scope answers. The two
English answerable false refusals are retained in the reported result rather than
hidden by reusing an earlier 100% artifact.

Evidence:

- `.quality-runs/2026-09-15-hardening-final2-store-schema3-retrieval.json`
- `.quality-runs/2026-09-15-hardening-final2-store-schema3-generation.json`
- `.quality-runs/2026-09-14-hardening-final3-store-schema3-generation.json`
- `.quality-runs/2026-09-14-hardening-final4-store-schema3-generation.json`
- `.quality-runs/2026-09-14-hardening-final5-store-schema3-generation.json`
- `.quality-runs/2026-09-15-spanish-canonical-route-fix-store-retrieval.json`
- `.quality-runs/2026-09-15-spanish-canonical-route-fix-store-generation.json`

The 2026-09-15 Spanish expense-route regression was also verified directly through
the rebuilt running service. “¿Cómo registro un gasto?” returned `ANSWERED`,
`HIGH`, and `SUFFICIENT`, cited only source `17006599` (`BOT Linux — día, efectivo,
mercancía y cierres`), and no longer exposed the canonical-question index page as
evidence.

### Developer

| Metric | Baseline | Final | Result |
|---|---:|---:|---|
| candidate hit@25 | 85.2941% | 85.0000% | diagnostic |
| hit@16 | 84.8765% | 85.1852% | diagnostic |
| section hit@16 | 82.3529% | 82.9412% | diagnostic |
| recall@25 | 73.5508% | 73.8365% | diagnostic |
| grounding acceptance | 90.4523% | 93.4673% | PASS |
| citation precision | 100.0000% | 100.0000% | PASS |
| refusal precision | 51.8987% | 69.7674% | diagnostic |
| out-of-scope answer rate | 31.6667% | 0.0000% | PASS |
| paraphrase consistency | 50.0000% | 100.0000% | PASS |
| project/department leakage | 0 / 0 | 0 / 0 | PASS |

Final generation contains 458 cases. English/Spanish grounding is
93.7500%/90.0000% (3.75-point gap), refusal precision is 56.6038%/90.9091%, and
both languages have zero out-of-scope answers. The final raw retrieval suite has
340 cases. English/Spanish hit@16 is 87.0748%/66.6667% (20.408-point gap): seven
Spanish questions miss an English gold candidate, two miss a Spanish gold
candidate, and one is a rerank miss. The evaluator deliberately omits live query
translation, and the 310/30 imbalance makes this a raw-evaluator residual rather
than evidence of live-route parity.

Evidence:

- `.quality-runs/2026-09-15-hardening-final2-developer-schema3-retrieval.json`
- `.quality-runs/2026-09-15-hardening-final2-developer-schema3-generation.json`

## EventType and Phase 4

The flag-free Phase 4 gate uses the serving route and prints its physical collection
before reading. Fresh execution passed:

- logical: `jira-stage-20260911-jira-complete-v3`
- physical: `jira-stage-20260911-jira-complete-v3-t2-0-9403f3e2ad8b`
- identifiers: 58/58
- indexed sections: 202/202
- POS login completion contract: present

The 2026-09-18 live corpus scan found **7,371 code chunks**. Its structured-code
profiles comprise **2,419 `data-class-field`**, **187 `enum-entry`**, and **58
`enum-registry`** chunks. Symbol metadata is present on **5,321/7,371** code
chunks. The remaining **2,050** are intentionally non-structured content: 2,047
`narrative` chunks and 3 `workflow` chunks. No structured-code profile is missing
symbol metadata, so the remainder is not an unexplained coverage gap.

A fresh `code_inventory_parameters` run against that live corpus passed **21/21**
answer contracts: all **19/19** answerable cases were grounded, both **2/2**
unanswerable cases refused, and no case failed the unique-inventory-bullet check.
The same run had zero cross-project and zero cross-department leakage. Its retained
artifacts are:

- `.quality-runs/2026-09-18-code-inventory-parameters-doc-refresh.jsonl`
- `.quality-runs/2026-09-18-code-inventory-parameters-doc-refresh-generation.jsonl`

Known limitation: intent routing for code-parameter questions remains sensitive to
exact vocabulary. Phrasing around an enum constant name versus a class name can
route the same underlying question to `STRUCTURED_INVENTORY`, `STRUCTURED_ENTITY`,
or `CODE_INVENTORY`. Session testing confirms that all three paths now produce
correct, grounded, non-duplicate answers (or an honest evidence refusal), but the
routing variability itself remains.

A focused live comparison against the checked-out source found 58 expected, 58
observed, and 58 exact EventType entries (coverage 1.0), with no missing or
mismatched entries.

The authoritative source is the live sibling checkout at
`../T3B/store-core-kotlin/shared/src/commonMain/kotlin/com/tiendas3b/shared/core/domain/model/event/EventType.kt`.
The coverage command below passes it with `--source`; a corpus-derived or recorded
snapshot is not an acceptable substitute.

## Latency and concurrency

The 32-request baseline was p50 18.075s, p95 40.677s, p99 47.079s. The final
post-rebuild run completed 32/32 with p50 **2.069s**, p95 **17.169s**, and p99
**26.626s**; no request exceeded 30 seconds.

| Stage | p50 | p95 | p99 |
|---|---:|---:|---:|
| generation | 0.002s | 5.124s | 5.432s |
| verification | 0.002s | 4.739s | 11.165s |
| retrieval | 0.726s | 5.127s | 8.412s |
| reranking | 0.672s | 4.736s | 7.877s |

Citation repair had one 3.043s observation. Final local-model concurrency remains
1: an eight-request concurrency-1 run passed 8/8 at p50 5.611s/p95 12.574s;
concurrency 2 passed 8/8 but worsened p50 by 11.8% for only a 2.4% p95 gain.

Evidence:

- `.quality-runs/2026-09-14-hardening-baseline-live-latency.json`
- `.quality-runs/2026-09-15-hardening-post-live-latency.json`
- `.quality-runs/2026-09-15-hardening-post-stage-latency.json`
- `.quality-runs/2026-09-15-hardening-concurrency-1.json`
- `.quality-runs/2026-09-15-hardening-concurrency-2.json`

## Exact reproducibility

Three separately labelled post-rebuild batches ran one live request ten times each.
Every batch produced 10/10 matching public-response fingerprints; all 30 responses
share one fingerprint. Mean latency was 3.494s, 3.354s, and 4.739s. The API key was
read only into each process and was neither printed nor persisted.

- `.quality-runs/2026-09-15-hardening-reproducibility-final-a.json`
- `.quality-runs/2026-09-15-hardening-reproducibility-final-b.json`
- `.quality-runs/2026-09-15-hardening-reproducibility-final-c.json`

## Live bilingual examples

Five cases ran through both `/v1/answer` and `/v1/answer/stream`; all ten requests
returned HTTP 200, and every stream's complete response exactly matched sync.

| Case | Result |
|---|---|
| Developer EN EventType identity | `LOGIN_POS_EVENT` -> `POS_LOGIN`, ID 101, version 0.3 |
| Developer ES EventType identity | same contract values in Spanish |
| Store EN reprint procedure | grounded three-step guidance |
| Store ES reprint procedure | grounded three-step guidance in Spanish |
| Developer EN unsupported “memoy” | `INSUFFICIENT_EVIDENCE`; no guess |

Raw requests and responses are in
`.quality-runs/2026-09-15-hardening-live-examples.json`. The English identity case
also verifies the generic registry-focused planner added when final live testing
found “identifier” retrieved the registry less reliably than “event id.”

## RAGAS status

RAGAS scores are intentionally not reported. The strict command fails before
scoring because one bilingual reference in `evaluation/ragas_dataset.example.jsonl`
is not marked human-reviewed:

```text
ValueError: bilingual references must be human-reviewed: 1
```

This is a data-governance blocker, not a fabricated score or application failure.

## Implementation and repository audit

Hardening removed a second streaming outcome-model call; added bounded deterministic
contract, procedure, and refusal paths; made local generation seeded and
single-candidate; batched reranking with safe OOM fallback; reused retrieval
embeddings; bounded federation/repair work; recomputed checkpoint state; and added
stage/queue telemetry. Silent vocabulary failures now log their exception.
Compatibility façade imports in workflow, planning, and query analysis are retained
because downstream imports fail without them; their public re-exports are explicit,
so Ruff remains clean without suppressions. No TODO/FIXME remains in the changed
production path.

Cleanup retained current architecture/operations docs, this quality record, and
cited evidence. Historical reports, scratch archives, caches, and generated build
trees were removed after reference checks.

`pyproject.toml` is the sole dependency declaration. The former hand-maintained
`requirements.txt` and `requirements-eval.txt` copies and all lint/format/type
ratchets were removed after repository-wide reference searches. Runtime, `dev`, and
`eval` dependencies install successfully from the project metadata. Deptry scans the
whole maintained tree. Its narrow configuration records only these tool limitations:

- Script-mode fallback imports (`run_retrieval_eval`, `build_gold_suites`,
  `phoenix_client`, `score`, and the learning-lab `starter`) are same-repository
  modules, not missing distributions.
- `uvicorn`, `coverage`, `deptry`, `import-linter`, `mypy`, `pre-commit`, and `ruff`
  are command-line entry points; `langchain-community` is an evaluation compatibility
  dependency imported indirectly by Ragas.
- `pytest` is correctly a development-only dependency even though deptry scans the
  test tree.

The test tree now mirrors ownership: application tests live under `tests/app/`, with
provider and workflow subpackages matching `app/`; evaluator, integration, labs, and
repository-tool tests have separate peer packages. The root retains only shared
fixtures and the cross-cutting architecture guard.

Real `.env` files remain ignored. Two checked-in templates are intentional, not
duplicates: `.env.example` is the complete local-development template, while
`.env.production.example` is the minimal production deployment contract with
production-safe hosts, endpoints, identity, and observability values. Neither file
contains a live credential.

Repository-wide quality checks are zero-tolerance: Ruff lint has 0 findings, Ruff
format has 0 unformatted files, application mypy has 0 errors, import-linter has 0
broken contracts, and deptry has 0 unexplained findings. Mypy uses no `type: ignore`
suppression. A small number of explicit `cast(...)` calls document library-boundary
facts that mypy cannot infer (LangGraph node overloads, validated routing/refusal
literals, and completed typed workflow state); each remains subject to runtime tests.

## Verification matrix

| Repository | Command | Final result |
|---|---|---|
| RAG | `.venv/bin/pytest -q` | 1,381 passed, 8 upstream Ragas warnings, 57.54s |
| Ingestion | `.venv/bin/pytest -q` | 313 passed, 2 warnings |
| Atlassian | ingestion venv `python -m pytest -q` | 25 passed |
| Backend | `.venv/bin/pytest -q` | full suite passed (about 185 tests) |
| Mobile | `./gradlew test` | BUILD SUCCESSFUL, 121 tasks |

Final `docker compose up -d --build` rebuilt API, RAG, ingestion, and Atlassian.
API, RAG, ingestion, Atlassian, and MongoDB are healthy; Chroma is running (the
compose service has no healthcheck). RAG `/health` and `/ready` return
`{"status":"ok"}`. The container uses `PI_RAG_LOCAL_MAX_CONCURRENCY=1`.

## Reproduction commands

```bash
.venv/bin/python -m evaluation.run_phase4_retrieval_gate --project-id T2.0

.venv/bin/python -m evaluation.scan_event_type_coverage \
  --source ../T3B/store-core-kotlin/shared/src/commonMain/kotlin/com/tiendas3b/shared/core/domain/model/event/EventType.kt \
  --project-id T2.0 --collection jira-stage-20260911-jira-complete-v3

.venv/bin/python -m evaluation.run_reproducibility_probe \
  --project-id T2.0 \
  --collection-name jira-stage-20260911-jira-complete-v3 \
  --question 'Which event id and version does LOGIN_POS_EVENT have?' \
  --runs 10 --batch-id release-a \
  --output .quality-runs/reproducibility-release-a.json

.venv/bin/python -m evaluation.run_ragas_eval \
  --input evaluation/ragas_dataset.example.jsonl \
  --output .quality-runs/ragas.json --require-bilingual-reviewed

.venv/bin/pytest -q
```

Supply `PI_RAG_INTERNAL_API_KEY` only in the process environment for live commands.
Do not print it or write it into an artifact.

## Manual verification

Use `http://127.0.0.1:8003`. Export the ignored local key as
`PI_RAG_INTERNAL_API_KEY`, then authenticate with
`Authorization: Bearer $PI_RAG_INTERNAL_API_KEY`. Never paste its value into a
checked-in file or transcript.

```bash
curl -sS http://127.0.0.1:8003/v1/answer \
  -H "Authorization: Bearer $PI_RAG_INTERNAL_API_KEY" \
  -H 'Content-Type: application/json' --data @request.json
```

For streaming, use the same body with `curl -N` against
`http://127.0.0.1:8003/v1/answer/stream`; it returns newline-delimited JSON ending
with a `complete` event.

Developer checks (`T2.0`, collection
`jira-stage-20260911-jira-complete-v3`, policy `project:T2.0`):

- EN: `What identifier and version does LOGIN_POS_EVENT have?`
- EN: `Which event id and version does LOGOUT_POS_EVENT have?`
- ES: `¿Qué identificador y versión tiene LOGIN_POS_EVENT?`
- ES: `¿Qué campos completos tiene LOGOUT_POS_EVENT?`
- refusal: `What does memoy mean in this project?`

Store checks (`T2.0-STORE`, collection `project-intelligence`, policies
`project:T2.0-STORE` and `department:T2.0-STORE:STORE_OPERATIONS`, department
`STORE_OPERATIONS`):

- EN: `How do I reprint?`
- EN: `What should I check before cancelling a sale?`
- ES: `¿Cómo reimprimo?`
- ES: `¿Qué debo revisar antes de cancelar una venta?`
