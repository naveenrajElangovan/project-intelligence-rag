# Implementation prompt — make the base enterprise-grade: adding a department must be configuration, not code

Repos: `~/Desktop/project-intelligence-rag`, `~/Desktop/project-intelligence-ingestion`,
`~/Desktop/project-intelligence-backend`.

**The test this document is written against:** onboarding *Finance and Accounting*, then *Purchasing and
Merchandising*, then five more, must be a project-configuration edit plus a re-ingestion — **zero lines
of application code, zero redeploys of logic, zero regex edits.** Today it is not: it requires changes in
two repos, and one of those changes silently breaks stale-document deletion.

Work the four parts in order. Part A is the blocking one — everything else assumes it.

Ship the three persona fixes from `35_STORE_VS_DEVELOPER_PERSONA_FIX_2026-09-07.md` **first**: they are
live user-facing defects, and they already follow the pattern this document generalises (behaviour
driven by the project's observed vocabulary rather than by literals in code).

---

## 0. Verified state — where the department model actually stands

The design exists and is good. It is one-third wired.

| layer | department support | evidence |
|---|---|---|
| **RAG** | **READY** | `retrieval_pipeline.py:287` accepts `department:{project}:*`; `_authorized_policy_filter` pushes it into the Chroma `$in`; `validate_authorized_candidates` re-checks it before rerank and before the LLM |
| **Ingestion** | **NOT WIRED** | `access_policy_id` is hardcoded to `f"project:{project_id}"` at `app/vector.py:113` and `:170`. `sourceAccessRules` appears in `corpora/T3B-COMPANY/project-configuration.example.json` and is read by **nothing** |
| **Backend** | **NOT WIRED** | `ProjectRecord` (`infrastructure/sql/models.py:42–54`) has no `source_access_rules` column. `chat_policy.retrieval_policies()` mints exactly `project:`, `user:`, `role:` — never `department:`. `entra_departments_claim` is read in `/v1/me` for **display only** and never reaches authorization |

The intended contract is already written down in `corpora/T3B-COMPANY/corpus-manifest.json`
(`sharedPolicy: "project:T3B-COMPANY"`, eight departments) and
`test-personas.json` (13 personas with `departmentScopes`, including a three-department manager and an
unauthorized user). **Build to that contract. Do not invent a second one.**

---

# PART A — Wire the department policy end to end

## A1 — Ingestion must stamp the policy the rules say, not the one the code assumes

**Files:** `app/vector.py`, `app/projects.py`, new `app/access_rules.py`

### Root cause

`_metadata()` writes `"access_policy_id": f"project:{document.project_id}"` unconditionally. There is no
path by which a Confluence page titled `[FINANCE_AND_ACCOUNTING] Expense policy` can ever be written
with `department:T3B-COMPANY:FINANCE_AND_ACCOUNTING`.

### The change

Add a small, total rule evaluator — no provider knowledge, no department names in code:

```python
# app/access_rules.py
@dataclass(frozen=True, slots=True)
class SourceAccessRule:
    provider: str          # CONFLUENCE | JIRA | GITHUB
    match_field: str       # TITLE | SPACE_KEY | LABEL | PATH
    prefix: str
    access_policy_id: str

def resolve_access_policy(
    rules: Sequence[SourceAccessRule], document: SourceDocument, shared_policy: str
) -> str:
    """First matching rule wins; no match means the project-shared policy."""
```

Then in `_metadata()`, replace the literal with `resolve_access_policy(...)`. Load the rules from the
project record alongside `vectorStore` in `app/projects.py` (which already parses `vectorStore` at
line 119).

**Validate the rules at load, fail closed:** every `access_policy_id` must be exactly
`project:{project_id}` or `department:{project_id}:{DEPT}` with `DEPT` matching `[A-Z0-9_]{2,64}`. A rule
naming another project, or a malformed policy, is a startup error — never a silently ignored line. This
is the one place a configuration typo could widen access, so it gets a hard gate rather than a warning.

### A2 — The deletion and reconciliation filters are a landmine; fix them in the same change

`app/vector.py` filters on the project policy in **four** places besides the writer:

```
:68   collection.delete(where={"$and":[{project_id}, {access_policy_id: f"project:{id}"}, {provider}]})
:84   {"access_policy_id": f"project:{project_id}"}
:148  _where(...)  -> same triple, plus source_id
```

The moment A1 starts writing `department:` policies, **every one of these stops matching those
documents.** Purge-and-reingest silently leaves them, and stale deletion — which the platform notes
already flag as `--full`-only for Jira/Confluence — misses them permanently. A deleted Finance page keeps
answering questions forever.

Replace the equality with a project-scoped match that covers every policy the project can mint:
filter on `project_id` (already present and sufficient for isolation) and drop `access_policy_id` from
the *delete* predicates entirely, or use `$in` over the project's full policy set. `project_id` is
written on every chunk and verified by `verify_project_collection`, so isolation does not weaken.

**Test:** ingest one document under a department rule and one under the shared policy; run the
provider purge; assert **both** are gone. This test fails today the moment A1 lands, which is the point.

## A3 — The backend must carry the rules and mint the scopes

**Files:** `app/infrastructure/sql/models.py`, `app/projects/*`, `app/api/project_configuration.py`,
`app/application/chat_policy.py`, `app/authorization/graph.py`

**A3a — carry the configuration.** Add `source_access_rules: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)`
to `ProjectRecord`, thread it through `ProjectDefinition` and the configuration API, and add the
migration. Without this the JSON in `corpora/` cannot reach ingestion at all.

**A3b — mint department scopes.** `chat_policy.retrieval_policies()` is four lines and is the entire
authorization surface for retrieval. It becomes:

```python
def retrieval_policies(
    project_id: str, user_id: str, roles: Sequence[str], departments: Sequence[str]
) -> tuple[str, ...]:
    """Immutable server-side retrieval scopes for one authorized user."""
    return (
        f"project:{project_id}",
        f"user:{user_id}",
        *(f"role:{project_id}:{role}" for role in dict.fromkeys(roles)),
        *(f"department:{project_id}:{d}" for d in dict.fromkeys(departments)),
    )
```

Departments come from the Graph custom security attribute set, **not** from the `departments` token
claim currently read in `/v1/me` — a claim the user's token carries is not an authorization source of
truth, and `/v1/me` uses it only to render a label. Extend `parse_project_access` to read a
`ProjectDepartments` attribute in the same `project:VALUE` shape `ProjectRoles` already uses.

**A3c — a user can hold more than one role and more than one department.** `parse_project_access`
currently does `roles[project_id] = role` into a `dict[str, str]` — **last assignment wins, one role per
project.** `test-personas.json` already defines `multi-department-manager` with three department scopes.
Change `project_roles` to `dict[str, tuple[str, ...]]` and add `project_departments` the same way. Every
caller that reads a single role (`/v1/me`'s `ProjectAssignment.role`, `chat.py`) takes the first for
display and the full tuple for policy.

### Proof for Part A — the persona matrix, and it must be a test, not a demo

Drive `test-personas.json` as a parametrised authorization test against a seeded two-department corpus:

- `shared-employee` sees shared documents and **no** department documents.
- each single-department persona sees shared + exactly its own department.
- `multi-department-manager` sees shared + exactly its three departments — this case cannot pass before
  A3c.
- `unauthorized-user` sees nothing and gets `PermissionError` at the RAG boundary, not an empty result.
- **Cross-department leakage is 0 in every direction**, asserted on `exposed_project_ids` *and* a new
  `exposed_access_policy_ids` field in the eval rows.

Adding a ninth department to the fixture must require **only** a new fixture entry.

---

# PART B — Get domain knowledge out of the code

You already hold this principle: `tests/test_corpus_agnostic_gate.py` scans every file under `app/` and
fails on the literals `POS` and `BOT`. That gate is right, and it is too narrow — it bans *entity*
names while the same file compiles *domain vocabulary* into regexes.

## B1 — Source-family routing is a project property, not a language property

`_source_route_intent` (`app/workflow_support/query_analysis.py:467`) decides which source family answers
a question using hardcoded bilingual word lists: `jira|issues|bugs|sprints|delivery|releases|priority|
assignees|entrega|incidencias|errores|prioridad`, and the same again for implementation and
cross-source. Adding Finance means the word `entrega` still means Jira, and adding Logistics means it
means goods movement — in the same deployment.

The persona fix already makes these branches conditional on the project's observed `source_types`. Finish
the job: move the **term lists themselves** into the vocabulary record that ingestion already writes
(`app/vector.py::_observed_vocabulary`), as an optional `intent_terms` map:

```json
{"record_kind": "__vocabulary__",
 "intent_terms": {"DELIVERY": ["jira","issue","sprint"], "IMPLEMENTATION": ["class","module"]}}
```

Code keeps the current lists as the **default when the project supplies none**, so nothing changes for
`T2.0`, and a new department that needs different routing ships a configuration value.

**Test:** a synthetic project whose `intent_terms` route `"entrega"` to `IMPLEMENTATION` does so, with
no code change and with `T2.0`'s routing byte-identical.

## B2 — Delete the hardcoded project identifier

`app/catalog_answers.py:9` — `if project_id != "T3B-COMPANY": return False`. A project id in an `if`
is the exact thing this document exists to remove. Drive it from a project capability flag
(`catalogReleasesEnabled` on the project record), or if the catalog path is not real yet, say so in the
module docstring and leave it unreachable deliberately rather than accidentally.

## B3 — Extend the corpus-agnostic gate to cover what it is actually protecting

Widen `test_corpus_agnostic_gate.py` from two entity literals to the class of thing:

- no project identifier literal anywhere under `app/` (`T2.0`, `T3B-`, `T2STORE`),
- no department-name literal (`STORE_OPERATIONS`, `FINANCE_AND_ACCOUNTING`, …) — read the list from
  `corpus-manifest.json` so the gate updates itself,
- no provider-specific business term outside the modules that own that provider.

The gate is the mechanism that keeps this property true after everyone has forgotten this document.

---

# PART C — Two caches that will not survive multiple departments

## C1 — The lexical corpus cache is keyed by user, and the startup warm-up never serves a request

`app/retrieval.py:920` keys the BM25 corpus cache on:

```python
key = (chroma_host, collection_name, project_id,
       tuple(sorted(self.access_policy_ids)), tuple(sorted(source_types)))
```

`access_policy_ids` always contains `user:{oid}`. Two consequences, both real today:

1. **The cache is per user.** Every distinct user builds and stores their own full corpus — up to
   `lexical_fallback_max_records = 20000` records with term-frequency maps — in a process-global dict
   with **no eviction**, only a TTL checked on read. Entries for users who stop asking are never
   reclaimed. With departments this becomes per (user × department set × source scope). This is an
   out-of-memory path, and the accelerator refuses CPU fallback, so it is a hard failure.
2. **`warm_authorized_lexical_corpora` is dead work.** It builds retrievers with
   `access_policy_ids=(f"project:{project_id}",)` (`app/retrieval.py:88`) — a key no real request ever
   produces, because real requests carry `user:` and `role:` too. Every startup pays the warm-up cost and
   every first real request still pays a full corpus build.

**The change:** key the corpus on the policies that can actually match a **document**. Ingestion writes
only `project:` and (after Part A) `department:` policies; `user:` and `role:` scopes never appear on a
chunk. Derive a `document_visible_policies` tuple — the project policy plus the caller's department
policies, sorted — and use that in both the cache key and the warm-up. Users in the same departments
then share one corpus, the warm-up key matches real traffic, and memory grows with the number of
*department combinations*, not users.

Add a bounded LRU on `_FALLBACK_CORPUS_CACHE` with an explicit maximum-entries setting, and emit its
size as a metric. An unbounded process-global cache is not an enterprise posture regardless of the key.

**Test:** two requests from different users with identical department scopes produce **one** corpus
build; different department scopes produce two; the warm-up key equals the key of the first real request
for that department set.

## C2 — Vocabulary cache, same key, same fix

`corpus_vocabulary()` (`app/retrieval.py:469`) keys on all `access_policy_ids` and passes
`limit=max(1, len(self.access_policy_ids))` to the `get`. With departments the caller holds more
policies, so the limit grows and the key fragments per user. Apply the same
`document_visible_policies` treatment; keep the limit tied to the number of **document-visible**
policies, since that is how many vocabulary records can exist.

---

# PART D — Operating a multi-department corpus

These are not code changes; they are the things that make the base survive contact with eight
departments and the people who own them.

1. **Schema version drift.** `corpus-manifest.json` and `project-configuration.example.json` say
   `schemaVersion: 4`; both live projects are `"3"`; RAG accepts `("4","3")`. Pick the target, cut over
   with `switch_pinecone_host.py`'s equivalent for Chroma, and make the deployed
   `PI_RAG_SUPPORTED_SCHEMA_VERSIONS` an asserted value rather than a default — a schema-4 namespace
   meeting a schema-3 reader is a 409, per department, at the worst moment.
2. **One gold suite per department, from day one.** The store corpus proved the cost of shipping a
   persona with no eval: three deterministic defects, invisible for weeks. Make "a department is not
   live until it has a gold suite and a leakage assertion" a written rule. The suites are cheap when the
   corpus is authored with citation anchors, as `docs/store-assistant/` already is.
3. **Per-department metrics.** `refusal_precision`, `no_answer_false_positive_rate` and
   `cross_project_leakage` split by department, in the existing Grafana dashboards. A department whose
   refusal precision collapses is the earliest signal that its corpus or its routing is wrong.
4. **A department onboarding runbook, and it must fit on one page.** If it does not — if it still says
   "then edit `query_analysis.py`" — Parts A and B are not finished.
5. **Departments live inside one project, not as sibling projects.** The manifest says so and the policy
   shape says so. Resist creating `T3B-FINANCE` as a project: it multiplies physical collections, BM25
   corpora, warm-ups and configuration rows by the number of departments, and it makes a
   cross-department question structurally impossible to answer for the manager persona who is entitled
   to one. `T2.0-STORE` existing as a separate project is defensible only because it is a different
   *audience* with a different corpus; do not let it become the pattern.

---

# Acceptance — the base is enterprise-ready when all of this is true

- Adding a ninth department is: one `sourceAccessRules` entry, one Entra attribute value, one
  re-ingestion. **No file under any `app/` changes.** Prove it by doing it in a test fixture.
- The persona matrix from `test-personas.json` passes in full, including the multi-department manager
  and the unauthorized user, with zero cross-department leakage asserted on policy ids.
- Purge-and-reingest removes department-scoped documents. (This test fails today the moment A1 lands.)
- The widened corpus-agnostic gate passes: no project id, no department name, no provider business term
  in application code.
- Two users in the same departments share one lexical corpus; the cache is bounded and its size is a
  metric.
- Every live department has a gold suite, and `refusal_precision` per department is on the dashboard.

## What this document does not claim

Part A's gaps were read directly from source and are unambiguous — the hardcoded policy literal, the
absent column, the four-line policy function, the single-role dict. Part C's per-user cache key and the
non-matching warm-up key were read from `retrieval.py:88` and `:920–925` and follow by inspection; they
have **not** been observed failing under load, because no load test exists — building one is part of
making Part C's claim a measurement rather than an argument. Nothing here moves a correctness threshold,
and nothing here weakens an authorization boundary: every change either adds a scope the RAG layer
already knows how to enforce, or removes a literal that prevented configuration from reaching it.
