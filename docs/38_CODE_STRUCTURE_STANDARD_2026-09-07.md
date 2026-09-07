# Implementation prompt — organisation-level Python structure for the three services

Repos: `~/Desktop/project-intelligence-rag`, `~/Desktop/project-intelligence-ingestion`,
`~/Desktop/project-intelligence-backend`.

This is a **structural** change with **zero behaviour change**. Every step is a move, a rename, or an
extraction. If any step changes what an answer says, that step is wrong.

---

## 0. Do this second, not first

**Prerequisite: `37_QUALITY_MEASUREMENT_AND_ENTERPRISE_BASE` Part 1 (the measurement layer) must land
before Part 3 of this document.**

A refactor of this size needs a regression harness that can prove behaviour is unchanged. Unit tests
prove modules still work; only the Layer 1 and generation lanes prove the *system* still answers the
same way. Right now those lanes cover one project and one topic. Refactoring 19,000 lines against that
is how a silent quality regression ships.

Parts 1 and 2 below (packaging, tooling, enforcement) are safe to start immediately — they add gates
without moving code.

---

## 1. Verified state — measured 2026-09-07

| | RAG | backend | ingestion |
|---|---|---|---|
| app lines / files | **18,993 / 49** | 5,470 / 58 | 6,207 / 29 |
| layering | none — one flat `app` package | **already layered** (`api` / `application` / domain pkgs / `infrastructure`) | none — flat |
| largest module | `workflow_nodes/answering.py` **2,684** | `api/integrations.py` 544 | `structured_chunking.py` **1,529** |
| top 5 modules | 8,281 lines = **44% of the service** | — | 3,439 = 55% |
| import cycles | **1** (`llm ↔ grounding`) | 0 | 0 |
| highest fan-in | `app.llm` (13 importers, 1,657 lines) | — | — |
| architecture tests | string/`len()` assertions | string assertions | **none** |

Tooling, all three repos: **no ruff, no mypy, no formatter, no import-linter, no coverage gate, no
pre-commit.** CI exists only in RAG and is one job: `pip install -r requirements.txt && pytest -q`.
All three use `pythonpath = ["."]` rather than installing the package — tests import a source tree, not
the artefact that ships.

### The single structural defect that explains the file sizes

```python
class AuthorizedRagWorkflow(EvaluationWorkflowMixin, PlanningNodesMixin,
                            RetrievalNodesMixin, AnswerNodesMixin):
```

The mixins read **eight attributes off `self` that they never declare** — `self._request` (103 uses),
`self._settings` (100), `self._vocabulary` (48), `self._generator` (39), `self._reranker` (17),
`self._grounding_verifier` (17), `self._retriever` (11), plus factories. There is no interface between
the parts, so every part can reach every other part, and a module can only grow. It is also why
`test_architecture.py` has to construct objects with `Mixin.__new__(Mixin)` and assign privates by hand
to test a router — a test that cannot use a constructor is telling you the constructor does not exist.

**Everything else in this document is downstream of replacing those mixins with explicit
collaborators.**

---

# PART 1 — Repository and packaging standard (all three services)

Do this first. It changes no application code and it is what makes Parts 2–4 enforceable.

## 1.1 `src/` layout, installed, never path-hacked

```
project-intelligence-rag/
├── src/pi_rag/…            # the package that ships
├── tests/
├── pyproject.toml
├── Makefile
└── .pre-commit-config.yaml
```

Rename the distribution and import name to a stable identifier per service — `pi_rag`, `pi_ingestion`,
`pi_backend`. A package named `app` cannot be installed alongside another package named `app`, cannot be
imported unambiguously, and makes every traceback ambiguous across three services.

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/pi_rag"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q --strict-markers --strict-config"
# no pythonpath: tests run against the installed package
```

Add `src/pi_rag/py.typed`. Install with `pip install -e ".[dev]"`. Do this as a single mechanical
commit — a `git mv` plus a project-wide `app.` → `pi_rag.` rewrite — with no other change in it, so the
diff is reviewable and revertable.

## 1.2 One toolchain, identical in all three repos

`pyproject.toml`:

```toml
[tool.ruff]
target-version = "py312"
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E","F","W","I","N","UP","B","A","C4","SIM","TID","PTH","RUF",
          "ANN","ASYNC","S","T20","ARG","PL","TRY","PERF"]
ignore = ["ANN101","ANN102"]
[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101","ANN","PLR2004"]
[tool.ruff.lint.flake8-tidy-imports]
ban-relative-imports = "all"
[tool.ruff.lint.pylint]
max-args = 6
max-statements = 40

[tool.mypy]
python_version = "3.12"
strict = true
warn_unreachable = true
disallow_any_explicit = false          # relax per-module, never globally
plugins = ["pydantic.mypy"]
[[tool.mypy.overrides]]
module = ["chromadb.*","sentence_transformers.*","langchain_ollama.*","docling.*"]
ignore_missing_imports = true

[tool.coverage.report]
fail_under = 85
exclude_also = ["if TYPE_CHECKING:", "raise NotImplementedError"]
```

`mypy --strict` on a 19,000-line codebase will produce thousands of errors on day one. **Do not fix them
all before proceeding.** Ratchet: enable strict for `domain/` and `application/` immediately (they are
small and pure), keep `infrastructure/` and `interface/` at default strictness, and add a CI check that
the error count never increases. The ratchet is the mechanism; a big-bang typing sprint is not.

`Makefile` — the same commands CI runs, so "works on my machine" and "passes CI" are the same statement:

```make
install: ; pip install -e ".[dev]"
fmt:     ; ruff format src tests
lint:    ; ruff check src tests && ruff format --check src tests
types:   ; mypy src
arch:    ; lint-imports
test:    ; pytest --cov=src --cov-report=term-missing
check:   lint types arch test
```

## 1.3 Dependency management

Pin every direct dependency with a compatible range in `pyproject.toml` (backend and ingestion already
do; RAG pins exact — keep exact for RAG's ML stack, that is correct for reproducible inference) and
generate a **lock file** with `uv lock` or `pip-compile`. Ship images from the lock, not from a loose
`requirements.txt`. Keep `requirements.txt` only if the Dockerfile needs it, and generate it from the
lock — never hand-edit two sources of truth. The backend already has a `pymongo`-missing-from-
`requirements.txt` bug for exactly this reason.

## 1.4 CI that runs the standard

One workflow per repo, jobs: `lint` · `types` · `arch` · `test` (matrix 3.12) · `build` (wheel + image)
· `sbom` (the existing `generate_sbom.py`). Branch protection requires all of them. Add
`.pre-commit-config.yaml` with ruff, ruff-format, and a large-file guard so the same gates run locally.

---

# PART 2 — The layering standard

One vocabulary for all three services, so a developer moving between them is never guessing.

```
src/pi_<service>/
├── domain/          entities, value objects, invariants, pure policy
├── application/     use cases + ports (typing.Protocol) — orchestration only
├── infrastructure/  adapters that implement ports: HTTP, Chroma, SQL, models
├── interface/       FastAPI routers, request/response DTOs, streaming, CLI
└── composition/     settings, DI wiring, app factory — the only place that knows all four
```

**The import rule, enforced by `lint-imports`, not by review:**

| layer | may import |
|---|---|
| `domain` | stdlib, `pydantic` — **nothing else, no framework, no I/O** |
| `application` | `domain`, stdlib, typing |
| `infrastructure` | `domain`, `application` (to implement its ports), third-party SDKs |
| `interface` | `domain`, `application`, `fastapi` |
| `composition` | everything |
| anything | **never** `composition`, except `main.py` |

`.importlinter`:

```ini
[importlinter]
root_package = pi_rag

[importlinter:contract:layers]
name = Clean architecture layers
type = layers
layers =
    pi_rag.interface
    pi_rag.application
    pi_rag.domain
containers = pi_rag

[importlinter:contract:domain-is-pure]
name = Domain imports no framework or SDK
type = forbidden
source_modules = pi_rag.domain
forbidden_modules = fastapi, chromadb, langchain_core, langgraph, httpx, sqlalchemy, pymongo

[importlinter:contract:no-cycles]
name = No import cycles
type = independence
modules = pi_rag.domain, pi_rag.application, pi_rag.infrastructure, pi_rag.interface
```

This replaces the string-matching in `tests/test_architecture.py` with a real import-graph check. Keep
the *behavioural* assertions in that file (`test_only_grounding_may_end_a_request_that_holds_documents`
is excellent and belongs in the test suite forever); delete the `len(...) <= 450` line counters, which
Part 3 makes obsolete.

---

# PART 3 — RAG: replace the mixins, then split along the seams

This is the work. Do it in the order below; each step is independently shippable and green.

## 3.1 Introduce an explicit context, delete the implicit `self`

Replace the four mixins with one frozen context passed explicitly:

```python
# application/rag/context.py
@dataclass(frozen=True, slots=True)
class RagContext:
    settings: RagSettings
    request: RagRequest
    vocabulary: CorpusVocabulary
    retriever: DocumentRetriever          # Protocol
    reranker: Reranker                    # Protocol
    generator: AnswerGenerator            # Protocol
    grounding: GroundingVerifier          # Protocol
    clock: Clock
```

Each former mixin becomes a small class taking `RagContext` in its constructor:
`QueryPlanner`, `EvidenceRetriever`, `AnswerComposer`, `WorkflowEvaluator`. `AuthorizedRagWorkflow`
becomes a composition root that builds those four and wires the graph — nothing else.

**Mechanical and safe:** convert one mixin at a time; `self._settings` becomes `self._ctx.settings`.
No logic moves in this step. When it is done, `test_architecture.py` can construct a router with a real
constructor and the `__new__` trick disappears.

## 3.2 Define the ports, in `application/ports/`

`DocumentRetriever`, `Reranker`, `AnswerGenerator`, `GroundingVerifier`, `Embedder`, `TelemetrySink`,
`Clock` — each a `typing.Protocol` with the two or three methods actually used. This is what breaks the
`llm ↔ grounding` cycle: both depend on a protocol in `application`, neither on the other.

## 3.3 Split the five god modules along seams that already exist

Nothing here is a new design — each file already contains these groups, separated by comment banners.

| today | becomes |
|---|---|
| `llm.py` **1,657** | `infrastructure/llm/client.py` (model construction, streaming, timeouts) · `infrastructure/llm/prompts.py` (templates) · `domain/refusals.py` (the 12 templated reason strings, both languages) · `application/evidence_assembly.py` (`_evidence_with_diagnostics`, truncation) |
| `workflow_nodes/answering.py` **2,684** | `application/rag/answer_composer.py` (node orchestration) · `application/answer/citations.py` · `application/answer/completeness.py` · `application/answer/coverage.py` · `domain/answer_contract.py` |
| `workflow_nodes/retrieval.py` **1,709** | `application/rag/evidence_retriever.py` · `application/retrieval/fusion.py` · `application/retrieval/scoping.py` · `application/retrieval/repair.py` |
| `retrieval.py` **1,181** | `infrastructure/chroma/retriever.py` · `infrastructure/chroma/collections.py` · `infrastructure/lexical/bm25.py` · `infrastructure/lexical/corpus_cache.py` |
| `workflow_support/query_analysis.py` **842** | `domain/intent.py` (routing policy, pure) · `domain/lexicon.py` (the term sets — which `37`'s Part B moves into project configuration) · `application/query/variants.py` |

**A file-size budget, enforced in CI:** 400 lines for `domain` and `application`, 500 for
`infrastructure` and `interface`. Not a style preference — a module that outgrows 400 lines has stopped
having one reason to change, and this codebase has five proofs of it.

## 3.4 Ingestion, same treatment

| today | becomes |
|---|---|
| `structured_chunking.py` **1,529** | `domain/chunking/` — one module per strategy (`code.py`, `markdown.py`, `html.py`, `csv.py`, `issue.py`) behind a `ChunkingStrategy` protocol, plus `application/chunking/router.py` that picks one by format |
| `atlassian.py` 638 | `infrastructure/atlassian/{client,confluence,jira,mappers}.py` |
| `service.py` 432 · `workflow.py` 239 | `application/ingestion/` use cases |
| `vector.py` 233 | `infrastructure/chroma/writer.py` + `domain/access_policy.py` (where `37` Part A's rule evaluator lands) |
| `content_security.py` 162 | `domain/content_security.py` — already pure, just move it |

The format-routed chunker is the clearest strategy-pattern candidate in the whole platform: one
protocol, five implementations, one registry. Adding a sixth format becomes a new file plus a registry
entry — the same "configuration, not surgery" property Part 3 of doc 37 asks for.

## 3.5 Backend — already close, finish it

The backend is the reference the other two should look like: `api` / `application` / domain packages /
`infrastructure` already exist and `test_architecture.py` already forbids `application → api`.
Remaining work is small:

- Rename `api` → `interface` for consistency across the three services (or rename the others to `api` —
  pick one word and use it everywhere).
- `conversations/store.py` (485) is infrastructure sitting in a domain package — move to
  `infrastructure/mongo/conversation_store.py`, leave `conversations/models.py` as the domain record.
- `api/integrations.py` (544) is one line under its own cap; split the OAuth callback flow from the
  connection CRUD.
- Promote `application/ports/` to the full port set — today it holds only `secrets.py` while
  `rag_client.py` talks HTTP directly from the application layer.
- Move the `department:`/`role:` scope construction from `37` Part A3 into `domain/access_policy.py`, so
  authorization scope shapes are domain rules with unit tests, not string formatting in a service.

---

# PART 4 — Conventions that make the structure survive

- **Naming.** `snake_case` modules, no plurals-vs-singular drift (`models.py` for records,
  `<thing>_repository.py`, `<thing>_client.py`, `<thing>_service.py`). No module named `utils`,
  `helpers`, `common`, or `misc` — those names are where layering goes to die. `workflow_support/` is
  already that module; Part 3.3 dissolves it.
- **Exports.** Every package `__init__.py` declares `__all__` with its public surface. Nothing outside a
  package imports a name prefixed `_`. The current `from app.workflow_support.query_analysis import
  _source_route_intent, _intent_source_scope, …` — 20 underscore-prefixed imports in `workflow.py` — is
  the clearest signal that these modules have no intended public API. Give them one; make the rest
  private for real.
- **Errors.** One exception hierarchy per service rooted at `PiRagError`, with `AuthorizationError`,
  `RetrievalError`, `GenerationError`, `ConfigurationError`. `interface` maps them to HTTP; no layer
  below it raises `HTTPException`.
- **Settings.** One `RagSettings` in `composition/`, injected. No module calls `get_settings()` at
  import time — that is what makes tests need env files.
- **Async discipline.** No blocking I/O in an `async def`; `asyncio.to_thread` at the adapter boundary
  only, which `infrastructure/` already does correctly for Chroma.
- **Logging and telemetry.** Structured, content-free, at the `interface` and `infrastructure`
  boundaries. `domain` and `application` never log — they return values. This preserves the
  content-free telemetry property `test_telemetry_privacy.py` already guards.
- **Tests mirror the source tree**: `tests/domain/`, `tests/application/`, `tests/infrastructure/`,
  `tests/interface/`, plus `tests/architecture/`. Domain and application tests need no fixtures, no
  network, no models — if one does, a dependency is pointing the wrong way.

---

# PART 5 — Migration plan

Ten pull requests, each green, each revertable, none changing behaviour.

| # | change | risk |
|---|---|---|
| 1 | Tooling: ruff, mypy (ratcheted), import-linter, coverage, pre-commit, CI jobs, Makefile — **no code moves** | none |
| 2 | `src/` layout + `app` → `pi_<service>` rename, one mechanical commit per repo | low, huge diff — review the command, not the diff |
| 3 | Create empty layer packages + `.importlinter` contracts; move the already-pure modules (`domain/content_security.py`, `domain/lexicon.py`, `chroma_collections.py`) | low |
| 4 | **RAG: `RagContext` + collaborators replace the mixins** (§3.1) | **highest — do it alone, ship it alone** |
| 5 | Ports as Protocols; break the `llm ↔ grounding` cycle | medium |
| 6 | Split `llm.py` | medium |
| 7 | Split `answering.py` | medium |
| 8 | Split `retrieval.py` (node) and `retrieval.py` (infra) | medium |
| 9 | Ingestion: chunking strategies + layer move | medium |
| 10 | Backend: finish the layering, port set, `domain/access_policy.py` | low |

**Every PR from #4 onward runs the full quality lanes before and after and attaches the diff.** Unit
tests will not catch a behaviour change in a 2,684-line module split; the eval lanes will. This is the
dependency on doc 37 Part 1, restated.

If a PR cannot be made to produce identical eval output, **revert it and split it smaller.** A refactor
that changes answers is not a refactor.

---

# PART 6 — Acceptance gate

- `make check` passes in all three repos: ruff clean, mypy error count at or below the ratchet,
  `lint-imports` green, coverage ≥ 85%, full suites green.
- **No module over its layer budget** (400 domain/application, 500 infrastructure/interface). Today five
  RAG modules and one ingestion module breach it by 3–7×.
- **Zero import cycles**, checked by `lint-imports`, not by inspection.
- `domain/` imports nothing but stdlib and pydantic — asserted, not reviewed.
- No public module imports an underscore-prefixed name from another module.
- The package installs and the tests run **against the installed wheel**, not a source path.
- **Layer 1 and generation output is byte-identical before and after the whole migration**, for `T2.0`
  and `T2.0-STORE`, both languages. This is the one gate that actually matters: it is what makes the
  claim "structural change only" true rather than hoped.

## What this document does not claim

Line counts, the import graph, the single `llm ↔ grounding` cycle, the fan-in and fan-out figures and
the mixin attribute counts were computed from the working tree on 2026-09-07. The target module split in
§3.3 is a **design proposal** based on reading those modules' existing internal groupings; the seams may
move once the work starts, and that is fine — the layer rule and the size budget are the invariants, not
the exact filenames. The effort estimate implicit in the ten-PR plan is not a measurement.
