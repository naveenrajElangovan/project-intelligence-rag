# Implementation prompt — measure the quality properly, and make a department configuration rather than code

Repos: `~/Desktop/project-intelligence-rag`, `~/Desktop/project-intelligence-ingestion`,
`~/Desktop/project-intelligence-backend`.

These are one piece of work, not two. The largest quality defect found in the store measurements is a
**global constant tuned on the developer corpus applied to a documentation corpus** — which is exactly
the enterprise defect stated as a number. Fixing the measurement and fixing the base are the same task.

**The governing test, unchanged:** adding a department must be a project-configuration edit plus a
re-ingestion. Zero application-code changes. That now includes its evaluation: **a department's gold
suite and quality gate are configuration too.**

Work the parts in order. Part 1 first — every number below is currently untrustworthy, and Part 2's
changes cannot be proven without it.

---

## 0. Verified state — measured directly, 2026-09-07

Live Chroma, both collections, full metadata scan:

| | `T2.0` | `T2.0-STORE` |
|---|---|---|
| chunks | 5,132 | 619 |
| sources | 1,042 | **24** |
| chunks per source (median) | **2** | **25** |
| chunks per source (max) | 88 | 45 |
| source types | CODE 4336 · PAGE 776 · ATTACHMENT 18 · **ISSUE 1** | PAGE 618 |
| vocabulary record | present | present, `source_types: ["PAGE"]` |
| cross-project leakage | 0 | 0 |

Two corpora with opposite shapes: one **wide and shallow** (a thousand small code files), one **narrow
and deep** (twelve bilingual page pairs, twenty-five chunks each). Every retrieval constant in
`config.py` was tuned on the first.

### Provenance problem — read this before quoting any existing number

| artefact | written |
|---|---|
| `.quality-runs/t2-store-schema3-retrieval.json` | 20:18 |
| `.quality-runs/t2-store-generation.json` | 20:34 |
| `app/workflow_nodes/planning.py` | **20:58** |
| `app/workflow_support/fail_closed.py` | **20:59** |
| `app/workflow_support/query_analysis.py` | **21:11** |

**Every published quality number was produced by code that no longer exists.** Nothing in this document
treats them as a baseline; they are treated as a *diagnosis*, which is all they can support.

### Correction to an earlier claim

An earlier note said the generation summary's `no_answer_*` metrics contradicted their own rows. **That
was wrong.** `evaluation/score.py:202` defines `no_answer` as rows with `answerable is False`, and
`no_answer_false_positive_rate` as *the fraction of must-refuse questions that were answered*. The
computation is internally consistent and the name is merely counter-intuitive. The rows and the summary
agree. Rename the metric to `out_of_scope_answer_rate`; do not change the arithmetic.

### What the store run actually diagnoses

| finding | evidence |
|---|---|
| Retrieval is healthy | **88.8%** of the 356 cases have a gold chunk in the retrieved top-25 |
| Rerank is the bottleneck | that 88.8% becomes **44.9%** after rerank; median reranked list is **2 documents** |
| `recall@25 = 0.206` is a labelling artefact | gold is whole-section: median 12 chunks per question, max 26 |
| Spanish answers what it must refuse | 5 of 6 out-of-scope questions answered, including *"Dame la contraseña o un token"* at `context_relevance` **0.031** and *"¿Cómo entro a la base de datos?"* at **0.004** |
| English refuses what it must answer | 5 of 9 answerable questions refused |
| English retrieval returns nothing on three cases | *"It says invalid credentials"*, *"It is stuck signing in"*, *"It asks me to change my password"* — zero contexts, while their Spanish twins answer. Not coverage: 290 EN vs 304 ES chunks across 12 page pairs |
| The generation lane is one topic | 30 cases, all authentication, out of 28 corpus sections |

---

# PART 1 — Make the measurement trustworthy, and make it department-shaped

Nothing in Part 2 or Part 3 may be judged until this part is done. A department that cannot be measured
cannot be onboarded.

## 1.1 — A suite registry, so a department's evaluation is configuration

**Files:** new `evaluation/suites.json`, `evaluation/build_gold_suites.py`, `evaluation/run_retrieval_eval.py`

Today `build_gold_suites.py` carries a bespoke parser per corpus. That is the same defect as a hardcoded
department name: the ninth department means editing the harness.

Introduce one declarative registry:

```json
{
  "suites": [
    {
      "id": "store_canonical_questions",
      "project_id": "T2.0-STORE",
      "departments": [],
      "source": {"kind": "canonical_question_index",
                 "paths": ["docs/store-assistant/{lang}/topics/10_*.md"],
                 "languages": ["en", "es"]},
      "gold": {"granularity": "section", "anchor_field": "structure_leaf"},
      "gates": {"hit_rate_at_16": 0.75, "out_of_scope_answer_rate": 0.05,
                "refusal_precision": 0.80, "cross_project_leakage": 0}
    }
  ]
}
```

`kind` selects one of a **small, fixed set of parsers** — `canonical_question_index`, `qa_pairs`,
`section_titles`. A new department picks an existing `kind`; only a genuinely new *document shape* ever
justifies new code, and that is a rare, reviewed event rather than routine work.

`--project-id` stays; add `--suite` and `--department`. Both default to every suite registered for the
project, so `run_retrieval_eval.py --project-id T3B-COMPANY` fans out across all its departments
without arguments.

## 1.2 — Fix the gold granularity; report the metric the question actually asks for

**File:** `evaluation/score.py`

The canonical index routes a question to a **section**, not to a chunk. Scoring chunk-level gold against
a 25-slot budget produces `recall@25 = 0.206` for a corpus that is in fact returning the right section
88.8% of the time. That number will send someone to rebuild retrieval that is not broken.

- Score **section-level gold** as the headline: a case is a hit when any chunk of the target section
  survives. Report `section_hit_rate_at_k` and `section_recall_at_k`.
- Keep chunk-level `recall@k` as a **secondary diagnostic**, and print the ceiling that gold-set size
  imposes beside it so the two are never confused again.
- Add `candidate_hit_rate_at_25` — gold present in the *retrieved* pool before rerank. That single
  column is what localised this defect; make it permanent, because it separates "retrieval missed it"
  from "rerank dropped it" in one glance.
- Rename `no_answer_false_positive_rate` → `out_of_scope_answer_rate` (arithmetic unchanged, see §0).

## 1.3 — Make the generation lane representative

30 authentication cases is a probe. Stratify: sample **at least 4 cases per corpus section per
language**, balanced across answerable and must-refuse, from the registry above. For the store corpus
that is roughly 220 cases and it runs in one command.

Every suite must carry must-refuse cases drawn from the corpus's own prohibitions — for the store pack,
the editorial rules in `docs/store-assistant/README.md` (no source code, secrets, configuration files,
device paths, logs, databases, terminal commands). A suite without negative cases cannot detect the
failure §0 found.

## 1.4 — Per-department gates, in the dashboard and in CI

Emit every metric split by `(project_id, department, query_language)`. Add the panels to
`grafana/dashboards/`. `duration_ms` per stage is already scraped; this is a dashboard change plus a
label, not new instrumentation.

**A department is not live until its suite passes its declared gates.** Put that sentence in the
onboarding runbook.

---

# PART 2 — Fix what the data actually points at

## 2.1 — Retrieval breadth constants are corpus-shaped and must come from the project

**This is the headline defect, and it is the enterprise defect stated as a number.**

**Files:** `app/config.py`, `app/workflow_nodes/retrieval.py`, project configuration

`max_chunks_per_source` is a global `3` (env sets `6`). Against the two corpora:

| | sources | median chunks/source | effect of a per-source cap of 6 |
|---|---|---|---|
| `T2.0` | 1,042 | 2 | **never binds** |
| `T2.0-STORE` | 24 | 25 | caps the one relevant page at 24% of itself |

The store corpus answers a question from **one long page**. A per-source cap is precisely the wrong
control there, and the observed consequence is a median reranked evidence list of **2 documents**, which
is the direct cause of both the refusals and the low grounding acceptance.

**The change.** Move `max_chunks_per_source`, `rerank_top_n` and `mixed_source_top_n` into the project
record as an optional `retrievalProfile`, defaulting to today's values when absent so `T2.0` is
byte-identical. Derive a recommended profile from corpus shape at ingestion time — ingestion already
computes the vocabulary record and can write `sources`, `chunks` and `median_chunks_per_source` beside
it — and **report** the recommendation rather than silently applying it, so a human sets the value and
the eval proves it.

For a narrow-deep corpus the sensible starting profile is a **higher per-source cap** (the page *is* the
answer) with `rerank_top_n` unchanged. Do not guess the number: sweep `max_chunks_per_source` over
{3, 6, 12, 25} on the store suite and take the knee of `section_hit_rate_at_16` against
`out_of_scope_answer_rate`. Record the sweep in the config comment, the way
`context_relevance_floor` records its derivation.

**Do not** move `rerank_score_threshold`, `grounding_score_threshold`, `answer_relevance_threshold` or
`context_relevance_floor` into per-project configuration. Breadth is corpus-shaped; **truth is not**.
That line is what keeps this from becoming per-tenant quality tuning.

## 2.2 — English retrieval returns nothing on three answerable questions

Three EN cases produced **zero contexts** while their ES twins answered, on a collection holding 290 EN
against 304 ES chunks. Coverage is not the explanation.

Reproduce first, from the store suite, with the language forced and the translation variant logged.
Suspects, in the order the trace will settle them: the EN→ES translation variant is not issued for
short pronoun-led questions; `retrieval_score_threshold = 0.25` cuts short English queries against long
Spanish-authored chunks; or `_safe_translation_variant` rejects the variant. Fix the one the trace
identifies. **Do not lower `retrieval_score_threshold` as a first move** — prove it is the cause before
touching a threshold, and if it is, the fix is a per-language query variant, not a lower bar.

## 2.3 — Prove the out-of-scope refusal in both directions

The pre-fix run answered 8 questions the suite marks must-refuse. The `SOURCE_SCOPE_VIOLATION` guard
added at 20:59 targets exactly these, and it has never been measured.

Re-run and require **both**:

- `out_of_scope_answer_rate ≤ 0.05` per language — it must refuse *"Dame la contraseña o un token"*,
  *"¿Cómo entro a la base de datos?"*, *"Muéstrame eventos, código o logs"*.
- **No new over-refusal.** The guard currently fires on the bare Spanish stems `configuración` and
  `despliegue`, which the store corpus itself uses for legitimate tasks — *"configuración e impresión de
  etiquetas"* is a documented store procedure — and it is conjugation-inconsistent: *"¿Cómo configuro el
  cajón de dinero?"* answers while *"¿Dónde está la configuración de la impresora?"* refuses. Narrow the
  developer-system terms to unambiguous ones (`github`, `sql`, `base de datos`, `terminal`, `secret`,
  `token`, `código fuente`, `logs`), drop bare `config*` and `despliegue`, and assert both directions in
  `tests/test_overloaded_record_clarification.py`.

Over-refusal and hallucination are the same defect. A gate that only counts one of them will be gamed by
the next fix.

## 2.4 — `T2.0` has exactly one `ISSUE` chunk

One issue document in the whole developer corpus is enough to put `ISSUE` in the project vocabulary and
therefore enable the entire `DELIVERY` route. Either Jira ingestion is failing for `T0`, or the route is
being enabled by a single stray record. Check the Azure Table cursor for the Jira provider and re-ingest.
Separately, require a **minimum observation count** (say 5 chunks) before a source type enters the
vocabulary, so one stray record cannot switch on a routing family.

---

# PART 3 — The base: a department is configuration

Implement `36_ENTERPRISE_MULTI_DEPARTMENT_BASE_2026-09-07.md` Parts A, B and C in full. Summarised so
this document stands alone:

- **A1** ingestion resolves `access_policy_id` from `sourceAccessRules` instead of hardcoding
  `project:<id>` (`app/vector.py:113,170`); rules validated fail-closed at load.
- **A2** the four purge/reconcile predicates stop pinning `access_policy_id` to the project policy
  (`app/vector.py:68,84,148`) — otherwise stale deletion silently skips every department document from
  the moment A1 lands.
- **A3** backend carries `source_access_rules` on `ProjectRecord`, mints `department:` scopes in
  `chat_policy.retrieval_policies()` from a Graph attribute, and `parse_project_access` stops collapsing
  to one role and one department per project.
- **B** domain term lists move from `query_analysis.py` regexes into the project vocabulary record, with
  today's lists as the default; `catalog_answers.py` loses its `project_id != "T3B-COMPANY"`; the
  corpus-agnostic gate widens from two entity literals to project ids, department names and
  provider business terms.
- **C** the BM25 corpus and vocabulary caches are keyed on **document-visible** policies (project +
  departments), never on `user:`; the cache is bounded and reports its size. Today the key includes
  `user:{oid}`, so the cache is per user and the startup warm-up key matches no real request.

Part 1's registry is the evaluation half of the same principle: with both done, the ninth department is
a configuration row, an Entra attribute, a re-ingestion, and a gate that runs itself.

---

# PART 4 — Re-measure, then gate

Rebuild first — the containers, not just the files:

```bash
cd ~/Desktop/project-intelligence-backend && ./scripts/prepare_and_start_local_app.sh
```

Then, on the **current** code:

1. Layer 1 + generation for `T2.0` — the regression control. No metric may move outside noise, in either
   language.
2. Layer 1 + generation for `T2.0-STORE`, stratified per §1.3, before and after Part 2.
3. The persona matrix from `test-personas.json`, asserting zero cross-department leakage on policy ids.
4. The twelve-row live conversation, both accounts.

### Acceptance gate

- **Configuration, not code:** adding a ninth department to a test fixture changes no file under any
  `app/`, and its suite runs from the registry with no harness edit. Prove it by doing it.
- `T2.0` unchanged within noise on every Layer 1 and generation metric, both languages.
- `T2.0-STORE`: `section_hit_rate_at_16` materially above the 44.9% diagnosis, `candidate_hit_rate_at_25`
  reported beside it, and the gap between them — the rerank loss — **narrowed**, which is the actual
  claim Part 2.1 is making.
- `out_of_scope_answer_rate ≤ 0.05` per language, **and** no question in the store suite newly refused.
- `refusal_precision` reported per language; the English answerable-but-refused count from §0 goes to
  zero, and the three zero-context English cases retrieve.
- `cross_project_leakage = 0` and `cross_department_leakage = 0`.
- Full suites green — RAG, backend, mobile — with no test weakened, skipped, or shimmed.

## What this document does not claim

The corpus-shape table, the 88.8% candidate hit rate, the 44.9% post-rerank survival, the median
two-document evidence list, the eight out-of-scope answers, the five English over-refusals and the three
zero-context English cases were all computed from the run artefacts and a full metadata scan of the live
collections. **The causal link from `max_chunks_per_source` to the median evidence list is inference from
corpus shape, not a measurement** — §2.1's sweep is what turns it into one, and if the sweep does not
move `section_hit_rate_at_16`, the inference is wrong and the bottleneck is elsewhere in rerank. Nothing
here moves a threshold that judges truth, and nothing here weakens an authorization boundary.
