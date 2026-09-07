# Standing engineering constraints — read this before changing the RAG platform

Undated on purpose. These are the rules the platform is held to, not a snapshot of its state.
Last confirmed against the working tree on 2026-09-07.

---

## 1. The base is enterprise, multi-department, and corpus-agnostic

**The governing test:** onboarding a new department — Finance, Purchasing, Logistics, the ninth one
nobody has thought of yet — must be a project-configuration edit plus a re-ingestion. **Zero lines of
application code. Zero regex edits. Zero redeploys of logic.**

This is not an aspiration to reach later. Any change that makes it *less* true is a regression, whatever
else it fixes.

Concretely, that means:

1. **No business vocabulary in application code.** No project ids, no department names, no
   provider-specific business terms, no domain word lists compiled into regexes. Behaviour is driven by
   the project's own observed vocabulary record — written by ingestion, read by RAG — or by project
   configuration. `tests/test_corpus_agnostic_gate.py` is the enforcement mechanism; widen it whenever
   a new class of literal appears, so the rule survives everyone forgetting this document.
2. **No behaviour that assumes a corpus has a source family.** A project with no issue tracker must
   never be routed to `ISSUE`; a project with no repositories must never be asked for `CODE`. Gate on
   the project's observed `source_types`, and treat an empty set as "not yet observed" so prior
   behaviour is preserved.
3. **Departments live inside one project**, scoped by `department:{project}:{DEPT}` access policies —
   not as sibling projects. Sibling projects multiply physical collections, BM25 corpora, warm-ups and
   configuration rows per department, and make a cross-department question structurally unanswerable for
   a manager entitled to one. The contract is written in `corpora/T3B-COMPANY/corpus-manifest.json` and
   `test-personas.json`; build to it, do not invent a second one.
4. **Authorization scopes are minted server-side, from Entra attributes, and never from the client or a
   token claim used for display.** The RAG boundary re-validates before rerank and before the LLM.
5. **Caches are keyed by what a document can be seen through, never by who is asking.** `user:` and
   `role:` scopes never appear on a chunk, so they must not appear in a corpus cache key. Every
   process-global cache is bounded and reports its size as a metric.
6. **A department is not live until it has a gold suite and a zero-leakage assertion.** The store corpus
   proved the cost of the alternative: three deterministic defects, invisible for weeks, because nothing
   measured that persona.

## 2. Correctness rules that outrank speed and outrank a fix

- **No threshold that judges truth moves for any other reason.** `grounding_score_threshold`,
  `answer_relevance_threshold`, `context_relevance_floor`: a faster or more helpful wrong answer is
  strictly worse than a slow refusal.
- **Only wasted or serialised work is removed.** The computation that produces an answer stays
  identical.
- **A fix must not create the opposite failure.** Over-refusal is the same defect as
  hallucination, wearing a safety badge. Every routing or gating change is tested in *both* directions:
  the questions it must stop refusing, and the questions it must not start refusing.
- **No test is weakened, skipped, or given a `getattr` shim to make it pass.** If a proof fails, the
  change is wrong.
- **Access-policy configuration fails closed.** A malformed or foreign policy id is a startup error,
  never a silently ignored line.

## 3. Open items carried forward

| item | state |
|---|---|
| Department policy end to end — ingestion writes it, backend mints it | **Not started.** RAG is ready; ingestion hardcodes `access_policy_id = project:<id>` (`vector.py:113,170`); backend has no `source_access_rules` column and `chat_policy` mints no `department:` scope. See `ENTERPRISE_MULTI_DEPARTMENT_BASE_2026-09-07.md` Part A |
| Ingestion purge filters pin `access_policy_id` to the project policy (`vector.py:68,84,148`) | **Not started — a landmine.** The day department policies are written, stale deletion silently skips those documents |
| One role and one department per project (`parse_project_access` → `dict[str, str]`) | **Not started.** The `multi-department-manager` persona cannot be expressed |
| BM25 corpus cache keyed per user; startup warm-up key never matches a real request | **Not started.** Unbounded process-global growth; warm-up is dead work |
| Domain word lists still compiled into `query_analysis.py` regexes | **Partially addressed.** Routing is now gated on observed `source_types`; the term lists themselves are still in code |
| `catalog_answers.py` hardcodes `project_id != "T3B-COMPANY"` | **Open** |
| Schema drift: manifest says `4`, both live projects are `3`, RAG accepts `("4","3")` | **Open** |
| **`SOURCE_SCOPE_VIOLATION` over-refuses ordinary Spanish store words** | **Open — introduced 2026-09-07 while fixing the store persona.** `configuración`, `despliegue` and `comandos` refuse before retrieval on a `PAGE`-only project. The store corpus itself documents "configuración e impresión de etiquetas" as a store task, so the refusal contradicts the corpus. It is also conjugation-inconsistent: `¿Cómo configuro el cajón de dinero?` answers, `¿Dónde está la configuración de la impresora?` refuses. Narrow the developer-system terms to unambiguous ones (`github`, `sql`, `base de datos`, `terminal`, `secret`, `token`, `código fuente`), drop the bare `config*` and `despliegue` forms, and prove it against the 368-case store gold suite in both directions |
| Backend `/v1/me` still orders assignments by `display_name` | **Open, now cosmetic** — the client no longer auto-selects when there is more than one assignment, so ordering only affects picker order |
