# Standing constraints and shared context — read this first

Undated on purpose: these are the rules the platform is held to, not a snapshot.
Both agents working on this platform — the implementing agent in the editor, and the
reviewing agent — work from this file. If the two ever disagree, this file wins, and the
disagreement gets resolved here before any code moves.

Last reconciled against the working tree: 2026-09-07, after the implementing agent challenged two
entries in section 6 and both challenges were upheld. **That is the process working.** Either agent may
challenge any line here by citing it; the reviewing agent verifies against the tree or the live system
and reconciles. A stale line in this file is a defect in this file, not a reason to work around it.

---

## 0. The targets, as given by the owner

Every piece of work on this platform serves these. They are listed in the order they were set.

1. **Both personas must work, with strict project isolation.** A store user
   (`store_user@…`) on `T2.0-STORE` and a developer (`developer@…`) on `T2.0`. Switching
   accounts must switch corpora cleanly. Zero cross-project leakage. Answers must be clean
   — no refusals of answerable questions, no half-finished replies.
2. **The base is enterprise, not per-user.** Nothing is built for one customer, one corpus
   or one department.
3. **Adding a department must be configuration, not code.** The governing test: onboarding
   Finance, then Purchasing, then the ninth department nobody has thought of yet, is a
   project-configuration edit plus a re-ingestion. Zero application-code changes, zero
   regex edits. **This includes its evaluation** — a department's gold suite and quality
   gate are configuration too.
4. **Validate before believing.** Reports are not evidence. A claim is checked against the
   working tree, the live system, or a re-run before it is accepted — by either agent,
   including about its own work.
5. **Measure all the quality.** Section-level metrics, candidate hit rate, per-language and
   per-department splits, out-of-scope answer rate. A number nobody measured is not a
   result.
6. **Organisation-level code structure.** Clean architecture, layered, enforced by tooling
   rather than by review. Large-scale Python conventions: `src/` layout, installed package,
   ruff, mypy, import-linter, coverage gate, CI.
7. **Readable with zero Python knowledge.** Every function documents what it does, where it
   runs, how it works end to end, what it gives back, and what happens when it fails —
   in plain language, no jargon.

**Nothing irreversible happens without a proven way back.** This was not stated as a target;
it was earned during the first destructive operation, and it now has the same standing.

## 1. Who does what

| | implementing agent (editor) | reviewing agent (Cowork) |
|---|---|---|
| writes application code | **yes** | no |
| runs the stack, Docker, the venv, migrations, ingestion | **yes** | no — isolated VM, no Docker, no stack access |
| reads the repos | yes | yes, directly |
| queries live Chroma / inspects live state | yes | yes, read-only |
| writes the implementation prompts and the standards docs | no | **yes** — into `docs/` and the Claude project |
| independently verifies the other's claims | yes | **yes — this is its main job** |
| approves destructive operations | never | never — **only the owner does** |

Both agents report what they could **not** verify, as plainly as what they could.

## 2. The enterprise rules

1. **No business vocabulary in application code.** No project ids, no department names, no
   provider-specific business terms, no domain word lists in regexes. Behaviour is driven by
   the project's observed vocabulary record or by project configuration.
   `tests/test_corpus_agnostic_gate.py` enforces it; widen it whenever a new class of
   literal appears.
2. **No behaviour that assumes a corpus has a source family.** A project with no issue
   tracker is never routed to `ISSUE`; a project with no repositories is never asked for
   `CODE`. Gate on observed `source_types`; an empty set means "not yet observed" and must
   preserve prior behaviour.
3. **Departments live inside one project**, scoped by `department:{project}:{DEPT}` policies
   — not as sibling projects. The contract is `corpora/T3B-COMPANY/corpus-manifest.json` and
   `test-personas.json`. Build to it; do not invent a second one.
4. **Authorization scopes are minted server-side from Entra attributes**, never from the
   client and never from a token claim used for display. The RAG boundary re-validates
   before rerank and before the LLM.
5. **Caches are keyed by what a document can be seen through, never by who is asking.**
   `user:` and `role:` scopes never appear on a chunk. Every process-global cache is bounded
   and reports its size.
6. **A department is not live until it has a gold suite and a zero-leakage assertion.**

## 3. Correctness rules that outrank speed, and outrank a fix

- **No threshold that judges truth moves for any other reason.** `grounding_score_threshold`,
  `answer_relevance_threshold`, `context_relevance_floor`. A faster or more helpful wrong
  answer is strictly worse than a slow refusal.
- **Only wasted or serialised work is removed.** The computation that produces an answer
  stays identical.
- **A fix must not create the opposite failure.** Over-refusal is the same defect as
  hallucination wearing a safety badge. Every routing or gating change is tested in both
  directions: what it must stop refusing, and what it must not start refusing.
- **Breadth is corpus-shaped; truth is not.** `max_chunks_per_source`, `rerank_top_n` and
  `mixed_source_top_n` may become per-project configuration. Truth thresholds may not — that
  line is what stops this becoming per-tenant quality tuning.
- **No test is weakened, skipped, or given a `getattr` shim to make it pass.**
- **Access-policy configuration fails closed.** A malformed or foreign policy id is a
  startup error, never a silently ignored line.

## 4. Operating rules for destructive work

Earned the hard way; they are not negotiable.

1. Commit and tag all repos before any irreversible step. A working tree is not a checkpoint.
2. Back up, then **prove the backup**: list its contents, not just its size. An 89-byte
   archive and a 57 MB archive both "exist".
3. Prove the restore path survives a deliberate recreate before relying on it.
4. Prove you can **re-fetch** before you delete. `scripts/verify_refetch.py` is that gate.
5. Purge plan-only first. `scopes` must be non-empty and `stateRowsDeleted > 0` — otherwise
   manifests survive, re-ingestion SKIPs everything, and an empty corpus reports success.
6. Verify with a live count, never with a tool's own success flag.
7. One project, one provider, per pass. `T2.0-STORE` before `T2.0`.
8. On any gate failure: stop and report. Never work around, never retry blindly.
9. **Order of enablement for any access-scoping change — learned from the 2026-09-08 incident.**
   A label that no caller's token can match does not protect a document, it **hides** it.
   The only safe order is: **(a)** the backend mints the scope, **(b)** the directory assigns
   the attribute to a real user, **(c)** verify a live user receives the scope, **(d)** only
   then stamp documents with it. Never stamp first. The proof that (a)–(c) hold is a live
   question from the real account, not a unit test.
10. **Chroma is busy, not dead, after a large delete.** Deleting hundreds of vectors blocks
   the heartbeat while the index rebuilds — measured at roughly 90 seconds, recovering on the
   sixth 30-second attempt, with `RestartCount 0` and no OOM or panic in the logs. Diagnose
   with `docker ps -a`, `docker logs`, `docker stats` and a bounded retry **before**
   concluding anything is broken. Restoring a backup over a merely busy database is how a
   recoverable pause becomes a real outage.
11. **A verification script that prints nothing has failed, not passed.** Every gate script
   emits an explicit result and exits non-zero when its dependency is unreachable.

## 5. State of play

**Verified by the reviewing agent** (read from the tree or the live system):

| | state |
|---|---|
| Per-project physical Chroma collections + `access_policy_id` filtering | correct, two independent boundaries, zero leakage |
| Store-persona routing defects (`DELIVERY` on a PAGE-only corpus, `ticket` clarification, first-turn fragments) | fixed, reproduced fixed by re-execution |
| Project picker, per-user selection in the client | implemented |
| Chroma persistence | **was writing to the container layer**; both compose files now mount `/data`; survived a forced recreate |
| Purge → re-ingest → restore loop for `T2.0-STORE / CONFLUENCE` | proven end to end, 619 chunks / 24 sources restored |
| Backups | 139 MB copy + 57 MB archive, SHA-256 recorded, held outside git |
| `T2.0` | untouched, 5,132 chunks / 1,042 sources |
| **Dark-corpus incident, 2026-09-08 — closed** | Department rules were seeded and the corpus re-stamped before the backend could mint a `department:` scope. 424 of 619 chunks became invisible to `store_user`, proven live: *"sobre el cierre de caja"* returned confidence `NONE`. The rules themselves were correct — a page-by-page prediction matched Chroma exactly, 195 shared + 424 department = 619. **The sequence was wrong, not the rules.** Recovered by removing the rules from the control plane, purging and re-ingesting; `T2.0` never touched. The same question now answers at confidence `MEDIUM` from a fresh chat. Rule 9 in section 4 exists because of this |
| Store corpus, current | 619 chunks / 24 sources / schema 3, **100% `project:T2.0-STORE`**, live-verified through the real store account |
| Control plane, current | both projects hold `source_access_rules=[]` — verified directly in `.local-sql/control-plane.db` |

**Reported by the implementing agent, not yet independently verified:** evaluation registry,
section-level metrics, 220-case stratified sampling, department/language metric splits,
retrieval-profile support, bounded caches, configurable intent vocabulary, multi-role and
multi-department Entra parsing, corpus statistics, five-chunk source-type activation,
department onboarding runbook, and the test counts (RAG 840, backend 124).

## 6. Open items

| item | state |
|---|---|
| Department policy end to end — ingestion stamps it, backend mints it | **in progress.** Ingestion side is written and verified (next two rows). Migration `20260907_0005` confirmed on a throwaway DB, on local SQLite, and on Azure SQL — both columns present, non-null, defaults `[]` and `{}`, two project rows. Remaining: seed the rules, enable stamping, and run the acceptance tests |
| Ingestion purge predicate | **RESOLVED — verified 2026-09-07 by the reviewing agent.** `delete_provider` is now `{"$and":[{"project_id"},{"provider"}]}`, `_source_filter` is project+provider+source_id, and neither pins `access_policy_id`. The chunk writer calls `resolve_access_policy(rules, document, shared_policy)`; the `__vocabulary__` SYSTEM record correctly keeps the project policy. Uncommitted. Its acceptance test still stands: stamp departments, purge, verify every department-scoped chunk is gone |
| Access-rule validation | **RESOLVED — verified 2026-09-07.** `access_rules.validate_source_access_rules` rejects an unsupported provider, an unsupported `matchField`, an empty prefix, and any `accessPolicyId` that is not `project:{id}` or `department:{id}:{DEPT}` matching the department pattern. Called from `projects.py:186` at load. Fail-closed, per project, as specified |
| **Two control planes exist — know which one the running stack reads** | `PI_DATABASE_URL` is local SQLite (`.local-sql/control-plane.db`) and that is what the running services use. Azure SQL is configured separately as `PI_DATABASE_URL_AZURE` and is reached only through a temporary process-only override. **Rules seeded into the wrong one silently do nothing**, which looks identical to "stamping is broken". Seed the control plane the stack actually reads, and state which one in every report |
| Azure SQL is serverless with 60-minute auto-pause | Expected behaviour, not a fault: the first connection after an idle period fails with ODBC `HYT00` while the database resumes, and succeeds ~30s later. `az sql db show` still reports `Online` throughout. Worth teaching `sync_sql_access.sh` (or the startup path) to retry on `HYT00` so this is not re-diagnosed by hand every time |
| `.env` `PI_DEV_SQL_RESOURCE_GROUP` | **RESOLVED — verified.** `.env` line 33 and `.env.example` line 36 both read `tiendas3b`; firewall sync reports "Azure SQL access is current" |
| `SOURCE_SCOPE_VIOLATION` over-refuses ordinary Spanish store words | **open.** `configuración` and `despliegue` refuse before retrieval on a PAGE-only project, while the corpus itself documents "configuración e impresión de etiquetas" as a store task. Conjugation-inconsistent: `¿Cómo configuro…?` answers, `¿Dónde está la configuración…?` refuses |
| `catalog_answers.py` hardcodes `project_id != "T3B-COMPANY"` | open — verify |
| Schema drift: manifest says `4`, both live projects are `3`, RAG accepts `("4","3")` | open |
| `T2.0` has exactly one `ISSUE` chunk | open — either Jira ingestion is failing for `T0`, or one stray record is enabling the whole `DELIVERY` route |
| Spanish ranking gap on `T2.0` (`ndcg@16` 0.175 es vs 0.407 en on equal recall) | open |
| Backend `/v1/me` orders assignments by `display_name` | open, now cosmetic — the client no longer auto-selects |
| Release compose Chroma mount | fixed in the file; **must be rolled out to production with a data migration first**, or recreating that container destroys its index |
| Department rules parked out of the seeder's path | **RESOLVED — verified 2026-09-08.** All 8 rules moved verbatim to `config/pending-department-rules/T2.0-STORE.sourceAccessRules.json` with a README stating the activation preconditions; `sourceAccessRules` removed from the active seed config; the real repair/seed path re-run at 15:06:50 and the control plane still reports 0 rules. The disarm is proven, not assumed |
| **`repair_local_project.sh` prints a JSON merge traceback and exits 0** | **open — same failure class as the incident.** A seeder that reports success after an unhandled error can apply a partial or wrong project record silently. It happened to land on the safe empty-rule state this time; that was luck, not design. A seed step must fail loudly and exit non-zero on any parse or merge error — this is rule 11 applied to the control plane |
| Backend does not mint `department:` scopes for a real user | **open, and it is the precondition for everything department-related.** `store_user` receives `project:T2.0-STORE`, `user:<oid>`, `role:T2.0-STORE:STORE_USER` — no department. Entra must carry the attribute and `chat_policy.retrieval_policies` must mint it, both verified live, before any document is stamped again |
| **A prose refusal is still counted as `answered`** | **open — the actual remaining defect, and the third instance of the same class.** Of the 5 store negatives reported as "answered when they must refuse", **3 are textbook refusals**: *"I cannot help with Windows, Android, or macOS because this assistant covers only visible POS and BOT operation for Linux stores…"*, its Spanish twin, and *"No puedo proporcionarte instrucciones para instalar o desplegar…"*. They decline and redirect exactly as the corpus editorial rules prescribe, yet carry `answered: true` and no `refusal_reason`. The true out-of-scope answer rate is **2/12 = 16.7%**, not 41.67%. Fix: the generator must emit a typed outcome when it declines in prose — the way `SOURCE_SCOPE_VIOLATION` and `UNVERIFIED_EVIDENCE` already do — and the metric must read that rather than the `answered` flag. Related inconsistency: *"How do I install or deploy?"* refuses via `UNVERIFIED_EVIDENCE` in English and via prose in Spanish |
| The two genuine out-of-scope answers | *"How do I change configuration?"* / *"¿Cómo cambio la configuración?"* both answer about **label print configuration**, which the store corpus does document. The question is ambiguous rather than clearly out of scope. Decide whether the suite label or the behaviour is wrong before changing either — and do not re-add a bare `config*` keyword guard, which is what caused the over-refusal this same word produced earlier |
| `max_chunks_per_source` is **not** the section-hit bottleneck — hypothesis disproven | Sweep {3, 6, 12, 25} → section_hit@16 44.66 / 44.94 / 44.94 / 44.94, candidate_hit@25 flat at 89.04. Cap 6 is the knee and higher caps add nothing. The reviewing agent's corpus-shape inference was explicitly labelled inference, and the measurement refutes it. The gap between 89.04% candidate hit and 44.94% section hit is therefore inside the **reranker**: `rerank_score_threshold` (0.10), `rerank_top_n` (16), and the cross-language gap (ES 0.40 vs EN 0.67) are the next levers |
| **`_deterministic_canonical_route_answer` preempted generation — RESOLVED 2026-09-08** | Root cause was sharper than suspected: the fallback ran **before** the model, so `generated is None` meant "no earlier deterministic answer", not a generator failure. **104 of 220 cases (47.3%) never reached the model at all** — stream timeouts 0, empty responses 0, model refusals 0. Moving it after generation: fallbacks 0/220, grounding acceptance 31.25% → 75.48%. Now carries `answer_style: canonical_quote`, a stage reason code, `pi_rag_canonical_quote_fallback_total{reason}` telemetry, and typed causes. A minimum-substance gate refuses one-line quotes and question echoes with `INSUFFICIENT_ANSWER_SUBSTANCE`. Original finding below, kept for the record |
| ~~`_deterministic_canonical_route_answer` emitting one-line non-answers~~ | **superseded by the row above.** Original observation, 2026-09-08: 87 of 169 answered cases (51%) have a body under 120 characters, and every one of them shares an identical signature: `answer_style: concise`, `valid_citation_count: 1`, `uncited_claims_dropped: 0`, `grounding_accepted: true`. Bodies include `"The table is empty."` returned to the question *"The table is empty."*, and `o un error de inicialización.` — a mid-sentence fragment. 99 of 169 answers open with an `### ` heading echoing the question. The fallback fires only when `generated is None` (`answering.py:1588`), so it may also be **masking a generator failure on half the corpus**. It carries no reason code, no telemetry and no distinct style, so it is invisible in every metric: verbatim quotes are trivially grounded (flattering `grounding_acceptance`), carry one real citation (flattering `citation_precision`), and count as `answered` (inflating `out_of_scope_answer_rate`). **Until it is instrumented, no generation-lane metric on this corpus can be trusted.** Confirm by giving it its own reason code and re-running |
| Store generation gates, read correctly | The six security-critical out-of-scope cases — secrets/tokens, database access, events/code/logs — **refused correctly in both languages**, with zero contexts retrieved and `SOURCE_SCOPE_VIOLATION` firing 10 times. There is no safety leak. The reported 50% out-of-scope answer rate counts refusal-shaped and degenerate bodies as answers |
| **The ingestion manifest does not carry `access_policy_id`, so a rule change never relabels** | **open — this is the one defect that breaks "a department is configuration".** `workflow.py:141–145` decides SKIP on version, `content_hash`, `parser_version`, `chunker_version`, `embedding_profile` and `schema_version`. The resolved access policy is in none of them and is not stored in the manifest at all (`state.py`). Add a department, change a prefix, or move a page between departments, then re-ingest incrementally: every unchanged document **keeps its old label** and the run reports success. `docs/38_DEPARTMENT_ONBOARDING_RUNBOOK.md` step 5 says "re-ingest the affected provider" without `--full`, so following the runbook exactly produces a silently mislabelled corpus. Fix shape: put the resolved policy (or a hash of the applicable rule set) in the manifest and in the SKIP comparison, so a rule change invalidates exactly the documents whose label would change |
| Vocabulary record is project-wide, not policy-scoped | **open, low severity.** `_observed_vocabulary` derives entities, doc categories and corpus stats from **all** project metadata, and the record is written with `access_policy_id = project:<id>`. A user without a department therefore receives terms derived from documents they cannot read — metadata rather than content, but it grows with every department added, and it can route them toward material they will then be refused. Scope the record per policy, or filter it at read time to the caller's visible policies |
| Account switching with departments | **VERIFIED SOUND 2026-09-08.** `projectBindingFor` handles 0/1/many; `projectSelectionsByUser` is keyed by `userId` and re-validated against the new session's assignments; `logout()` resets the whole UI state and the conversation sequence. Adding departments changes none of this. One operational note: after a department attribute changes in Entra, the RAG vocabulary and BM25 caches hold the old visibility for up to `lexical_fallback_cache_ttl_seconds` (300s default) |
| Cache keying and bounding | **RESOLVED — verified.** `document_visible_policies` is used in both the vocabulary and BM25 cache keys, so `user:` and `role:` no longer fragment them; `_FALLBACK_CORPUS_CACHE` is an `OrderedDict` LRU bounded by `lexical_fallback_cache_max_entries` (default 64) with the size exposed. Closes the doc-36 Part C item |
| Two documents numbered `38_` | `38_CODE_STRUCTURE_STANDARD_2026-09-07.md` and `38_DEPARTMENT_ONBOARDING_RUNBOOK.md`. Renumber one |
| Code structure standard (`38_…`) and documentation standard (`01_…`) | written, not started. No repo has ruff, mypy, import-linter, a coverage gate or pre-commit; all three still use `pythonpath = ["."]` and a package named `app` |

## 7. The document set

| file | what it is |
|---|---|
| `docs/00_ENGINEERING_CONSTRAINTS.md` | this file — read first |
| `docs/01_DOCUMENTATION_STANDARD.md` | every function readable with zero Python knowledge |
| `docs/35_STORE_VS_DEVELOPER_PERSONA_FIX_2026-09-07.md` | the two-persona defects and their fixes |
| `docs/36_ENTERPRISE_MULTI_DEPARTMENT_BASE_2026-09-07.md` | department = configuration, end to end |
| `docs/37_QUALITY_MEASUREMENT_AND_ENTERPRISE_BASE_2026-09-07.md` | the measurement layer and what it points at |
| `docs/38_CODE_STRUCTURE_STANDARD_2026-09-07.md` | clean architecture for the three services |
