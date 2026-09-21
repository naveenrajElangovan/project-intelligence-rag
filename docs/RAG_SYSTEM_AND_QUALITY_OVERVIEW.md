# Project Intelligence RAG — What It Is and How We Know It Works

*A plain-language guide for readers with no prior RAG background. Last aligned with `docs/CURRENT_ARCHITECTURE.md` and `docs/QUALITY_STATUS.md` as of 2026-09-19.*

---

## 1. What problem does this system solve?

Imagine a company has thousands of internal documents: store procedures, engineering wikis, Jira tickets, source code. Employees and internal tools want to *ask questions in plain English or Spanish* and get a correct, trustworthy answer — not a 40-page document to search through themselves.

The tempting shortcut is to just ask a general-purpose AI chatbot. The problem: a general chatbot doesn't know this company's private procedures, and worse, it will confidently **make things up** ("hallucinate") when it doesn't actually know the answer.

This project solves that problem using a technique called **Retrieval-Augmented Generation (RAG)**:

1. **Retrieve** — first, search the company's own documents for the specific passages relevant to the question.
2. **Augment** — hand those exact passages to the AI model as its only allowed source of truth.
3. **Generate** — the AI model writes an answer, but it is only allowed to say things that are directly supported by those passages, and it must say exactly which passage backs up each part of the answer.

If the documents don't contain a good answer, the system is designed to **say "I don't know" rather than guess**. That single design choice — refusing to guess — is the difference between a toy demo and something a business can actually rely on, and a large part of this document is about how we *proved*, with real measurements, that the refusal behavior and the answers themselves work correctly.

This repository (`project-intelligence-rag`) is the backend microservice that does steps 1–3. It is never called directly by end users — only by the company's own backend, which is responsible for authenticating the user and telling this service which projects/departments that user is allowed to see.

---

## 2. The big picture: how a question becomes an answer

```
                 ┌─────────────────────────────────────────────────────────┐
                 │                     Company Backend                      │
                 │   (authenticates the user, decides what they can see)    │
                 └───────────────────────────┬───────────────────────────────┘
                                              │ "authorized question"
                                              ▼
                 ┌─────────────────────────────────────────────────────────┐
                 │              THIS SERVICE: project-intelligence-rag       │
                 │                                                           │
                 │  1. Understand the question (language, intent, follow-up)│
                 │  2. Search the vector database for relevant passages      │
                 │  3. Re-rank and fuse those passages by true relevance     │
                 │  4. Check whether the evidence is actually complete       │
                 │  5. Ask the AI model to answer using ONLY that evidence   │
                 │  6. Verify every claim in the answer against the evidence │
                 │  7. Return a structured, cited, fail-closed response      │
                 └───────────────────────────┬───────────────────────────────┘
                                              │
                                              ▼
                             Chroma (vector database of company documents,
                              written only by a separate ingestion service —
                              this service never writes to it)
```

Every answer this service produces ends in exactly one of five outcomes. This is called the **answer contract**, and it's the backbone of the whole system's trustworthiness:

| Outcome | Meaning in plain English |
|---|---|
| `ANSWERED` | We found solid evidence and the answer is fully backed by it. |
| `NEEDS_CLARIFICATION` | The question is ambiguous — we ask the user to be more specific instead of guessing. |
| `INSUFFICIENT_EVIDENCE` | We searched, but the documents don't actually contain the answer — so we say so instead of inventing one. |
| `SOURCE_CONFLICT` | Two documents disagree, so we flag the conflict instead of arbitrarily picking one. |
| `ACCESS_DENIED` | The question falls outside what this user/project is authorized to see. |

There is no sixth, silent option where the system falls back to the AI model's own general knowledge. That fallback path simply does not exist in the code — it's a structural guarantee, not a prompt instruction that could be ignored.

---

## 3. Walking through the pipeline, stage by stage

### Stage 1 — Understand the question
*Files: [`app/workflow_nodes/planning.py`](../app/workflow_nodes/planning.py), [`app/llm.py`](../app/llm.py) (`BilingualQueryPlanner`, `ConversationQueryResolver`)*

Before searching anything, the system figures out:
- What language is this in (English or Spanish)? The company operates bilingually, so this matters for both search and the reply.
- Is this a follow-up to a previous question ("what about the second one?")? If so, resolve it into a standalone question first.
- What *kind* of question is this — a simple lookup, a "list everything" request, a procedure question, a code/parameter question? Different kinds get routed differently later.

It then builds a small, deliberately bounded **query plan**: the English version of the question, plus a Spanish translation if needed, so the search step can find matches regardless of which language the source document was written in.

### Stage 2 — Search the vector database
*Files: [`app/retrieval.py`](../app/retrieval.py), [`app/chroma_collections.py`](../app/chroma_collections.py)*

Documents aren't stored as plain text for searching — they're stored as **embeddings**: long lists of numbers produced by an AI model (`multilingual-e5-large`, run locally) that capture the *meaning* of a passage, not just its exact wording. This lets the system find a passage about "reprinting a receipt" even if the question says "how do I print it again."

Two safety properties matter here:
- **Every project gets its own physical database collection**, named with a hash so a naming mistake can't silently point one project at another project's data (`verify_project_collection()` fails loudly if the wrong collection comes back).
- **Every search is filtered by the caller's authorized project/policy IDs at the database level** — not just checked afterward. This is one of several independent layers preventing one customer's data from leaking into another's answer (see Section 5).

### Stage 3 — Combine keyword and meaning-based search
*Files: [`app/retrieval_pipeline.py`](../app/retrieval_pipeline.py), [`app/lexical_tokens.py`](../app/lexical_tokens.py)*

Meaning-based ("semantic") search is powerful but can miss exact technical terms — for example, an exact code constant like `APP_CLOSE_SHIFT_EVENT`. So the system *also* runs a classic keyword search (BM25) in parallel, with a custom tokenizer that splits compound identifiers (`APP_CLOSE_SHIFT_EVENT` → also matches `shiftSummary`, `shift_summary`) while keeping the whole token too.

The two result lists (semantic + keyword) are then merged using **Reciprocal Rank Fusion**, a well-established way to combine two ranked lists so a passage that scores well on *either* signal has a good chance of surviving, rather than requiring both to agree.

### Stage 4 — Re-rank for real relevance
*File: [`app/reranking.py`](../app/reranking.py)*

The first-pass search is fast but approximate. A second, more expensive model — a **cross-encoder** (`bge-reranker-v2-m3`, also run locally rather than sent to a third party) — looks at the question and each candidate passage *together* and produces a much more accurate relevance score. This runs in batches for speed and caches results, since the same (question, passage) pair always scores the same way.

One subtlety worth calling out: tables in source documents don't read like prose, so the cross-encoder (trained mostly on prose) was scoring correct table answers too low. [`app/table_evidence.py`](../app/table_evidence.py) rewrites each table row into a full sentence ("Column X for row Y is Z") purely for scoring/re-ranking purposes — the *original* table is still what gets shown to the AI model for the final answer, so the reply can still reproduce the table exactly.

### Stage 5 — Check whether the evidence is actually enough
*Files: [`app/workflow_support/completeness.py`](../app/workflow_support/completeness.py), [`app/workflow_nodes/retrieval.py`](../app/workflow_nodes/retrieval.py)*

Before ever calling the AI model to write an answer, the system checks: does the retrieved evidence actually cover everything the question asked for? If the question asks for "all the fields of X" and only 3 of 5 fields were found, that's incomplete. If evidence is incomplete, the system is allowed **exactly one** additional, more targeted search ("repair retrieval") — not an unbounded retry loop — before it gives up and returns `INSUFFICIENT_EVIDENCE`.

### Stage 6 — Generate the answer (only from the evidence)
*Files: [`app/llm.py`](../app/llm.py), [`app/model_gateway.py`](../app/model_gateway.py), [`app/workflow_nodes/answering.py`](../app/workflow_nodes/answering.py)*

Now, and only now, the AI model is asked to write an answer — and it is given *only* the retrieved passages, never told to rely on its own training knowledge. The model must tag each part of its answer with a `[SOURCE n]` marker pointing to a specific passage. `app/model_gateway.py` routes this call through a bounded router (LiteLLM) that supports Ollama (local), OpenAI, or Azure OpenAI, decided purely by validated configuration — nothing about which model to call is guessed at runtime.

For certain question types — like "give me the complete product catalog" — the system skips the AI model entirely and renders a **deterministic answer** directly from the structured data ([`app/catalog_answers.py`](../app/catalog_answers.py), [`app/workflow_support/deterministic_answers.py`](../app/workflow_support/deterministic_answers.py)). Large enumerations are exactly where a language model is most likely to truncate a list or subtly alter an item, so for these cases the system prefers a plain, template-based answer that cannot hallucinate.

### Stage 7 — Verify the answer before releasing it
*Files: [`app/grounding.py`](../app/grounding.py), [`app/grounding_contract.py`](../app/grounding_contract.py), [`app/workflow_support/citations.py`](../app/workflow_support/citations.py)*

This is the step that catches the AI model if it still says something unsupported, despite the instructions in Stage 6. Nothing is released to the caller until it passes **all** of the following checks:

| Check | What it catches |
|---|---|
| Citation-index validation | The answer references a `[SOURCE n]` that doesn't exist, or a source is unused/mismatched. |
| Claim grounding | Each individual claim is compared against its cited passage using semantic similarity plus deterministic exact-value/negation checks — a claim that isn't actually supported gets pruned, not replaced with an invented one. |
| Requested-item completeness | The answer is missing something the question explicitly asked for. |
| Exact-anchor validation | For identifier/value-style answers, the exact value in the answer must literally appear in the cited evidence. |
| Cross-source rules | Conflicting evidence across sources is flagged rather than silently resolved by picking one. |

If a claim fails grounding, it is **removed from the answer** rather than being replaced with a guess — so a partially-grounded answer degrades gracefully instead of failing outright or fabricating a fix.

### Stage 8 — Return a fail-closed, structured response
The final response always maps to one of the five outcomes from Section 2, and the whole thing is orchestrated as a bounded **LangGraph** state machine ([`app/workflow_graph.py`](../app/workflow_graph.py), [`app/workflow.py`](../app/workflow.py)) — meaning the sequence of steps above is an explicit, inspectable graph of nodes and edges, not an open-ended loop that could run away or take an unexpected path.

---

## 4. How do we know this actually works? (Production-grade quality testing)

Anyone can *build* a RAG pipeline that looks right. The harder, more important part is *proving* — with numbers, not vibes — that it retrieves the right evidence, refuses when it should, never leaks data across customers, and answers consistently. That proof lives in the `evaluation/` directory (~35 scripts) and is summarized with real measured numbers in [`docs/QUALITY_STATUS.md`](../docs/QUALITY_STATUS.md).

### 4.1 The core idea: gold-standard test suites

The team built **hand-verified question sets** ("gold suites") for two real corpora in the system:

- **Store** — day-to-day retail operations questions (e.g. "How do I reprint a receipt?").
- **Developer** — internal engineering/technical questions (e.g. "What identifier and version does `LOGIN_POS_EVENT` have?").

For every question in a gold suite, humans recorded the *correct* passage(s) that should be retrieved, and for many, the correct final answer. Each suite exists in **both English and Spanish**, since the system must behave correctly in both languages, not just the one it was mostly built/tested in.

An automated harness then runs the *entire* pipeline against every question and grades the result against several independent metrics, described below in plain terms.

### 4.2 What gets measured, and why each metric matters

| Metric | Plain-English meaning | Why it matters |
|---|---|---|
| **hit@16 / section hit@16** | Out of the top 16 retrieved passages, did the correct one show up? | If the right passage never gets retrieved, no amount of good writing can produce a correct answer — this is the foundation everything else depends on. |
| **recall@25** | Of all the correct passages that exist for a question, how many were found in the top 25? | Some questions need *multiple* passages (e.g. "list all fields"); this catches partial retrieval. |
| **grounding acceptance** | Of the answers produced, what fraction had every claim actually supported by cited evidence? | This is the direct hallucination check — the central promise of the whole system. |
| **citation precision** | Of the citations attached to an answer, what fraction point to evidence that's genuinely relevant? | Catches "correct answer, wrong/fake citation," which is just as damaging to trust as a wrong answer. |
| **refusal precision** | When the system says `INSUFFICIENT_EVIDENCE`, was that the *right* call (i.e., the answer genuinely wasn't in the documents)? | A system that refuses too often is useless; a system that never refuses is dishonest. This measures whether refusals are trustworthy, not just frequent. |
| **out-of-scope answer rate** | For questions that have *no* correct answer in the corpus, how often did the system answer anyway instead of refusing? | The direct, adversarial hallucination test — deliberately asking about things that don't exist. |
| **cross-project / cross-department leakage** | Did any answer ever include evidence from a different project or department than the one authorized? | This is a data-isolation/security guarantee, not just a quality one — a single leak here would be a serious incident in a multi-tenant system. |
| **paraphrase consistency** | Does asking the same question in different words produce the same underlying answer? | Catches brittleness — a system that only works for the exact phrasing testers happened to use isn't production-ready. |
| **reproducibility** | Does the exact same request, run multiple times, produce the exact same response? | For a system making operational decisions, non-determinism (getting a different answer to the identical question) undermines trust even if each individual answer is plausible. |

### 4.3 The actual measured results (as of 2026-09-18)

These are real numbers from retained evaluation artifacts (`.quality-runs/*.json`), not projections:

**Store corpus** (356 retrieval cases, 368 generation cases):

| Metric | Result | Gate |
|---|---:|---:|
| hit@16 | 100.0% | ≥ 75% |
| grounding acceptance | 99.44% | ≥ 85% |
| citation precision | 100.0% | 100% |
| refusal precision | 85.71% | ≥ 80% |
| out-of-scope answer rate | 0.0% | ≤ 5% |
| cross-project / cross-department leakage | 0 / 0 | 0 / 0 |

**Developer corpus** (340 retrieval cases, 458 generation cases):

| Metric | Result | Gate |
|---|---:|---:|
| grounding acceptance | 93.47% | ≥ 85% (PASS) |
| citation precision | 100.0% | 100% (PASS) |
| paraphrase consistency | 100.0% | PASS |
| out-of-scope answer rate | 0.0% | PASS |
| cross-project / cross-department leakage | 0 / 0 | PASS |

**Honesty about known limitations** — the quality report explicitly documents a residual issue rather than hiding it: the raw Developer retrieval test set is imbalanced (310 English cases vs. 30 Spanish cases) and doesn't use the same live translation step the real service uses, producing an apparent English/Spanish retrieval gap (87.07% vs. 66.67% hit@16) in that *specific offline test*. Direct testing of the live, running service in both languages does **not** show this gap. This distinction — a limitation in the *test harness* versus a limitation in the *product* — is called out explicitly rather than blended into one misleading number. The team's stated policy is: "Never change truth thresholds merely to make a run pass" — gates get met by fixing the system, not by relaxing the bar.

### 4.4 Beyond correctness: latency, concurrency, and reproducibility

Being correct isn't enough for production — it also has to be fast enough and behave predictably under load:

- **Latency**: after a round of hardening work, a 32-request baseline improved from p50 18.1s / p95 40.7s to p50 **2.07s** / p95 **17.2s**, with no request exceeding 30 seconds.
- **Concurrency**: local model concurrency is fixed at 1, based on measurement — testing concurrency 2 made typical-case latency 11.8% *worse* for only a 2.4% improvement in worst-case latency, so the team kept the setting that measurably performs better rather than the one that sounds more scalable.
- **Reproducibility**: the same live question was sent 10 times each in three separate batches (30 requests total). All 30 responses produced the identical response fingerprint — meaning the system's output is deterministic for a fixed input, which matters for anyone building automation or trust on top of these answers.
- **Bilingual live check**: five real questions were sent through both the regular and the streaming API in both English and Spanish (10 requests total); every one returned successfully, and every streamed response exactly matched its non-streamed equivalent.

### 4.5 A second, independent judge: RAGAS

In addition to the team's own hand-built gold suites, the evaluation suite integrates **Ragas**, a widely-used third-party framework for scoring RAG systems on faithfulness, answer relevancy, and answer correctness — an external check that doesn't share the same blind spots as an in-house test suite. At the time of the last report, the strict Ragas run was intentionally blocked by a data-governance rule (one bilingual reference item hadn't yet been human-reviewed) — the run fails loudly rather than silently reporting a score built on unverified reference data. That's treated as a governance gap to close, not swept under the rug.

### 4.6 Code-level safety nets (not just test suites)

Some of the most important protections are structural, enforced directly in code every time the system runs — not just something a test suite checks after the fact:

- **Credential-value questions are refused by construction** — [`app/workflow_support/fail_closed.py`](../app/workflow_support/fail_closed.py) pattern-matches for password/PIN/token/secret-style requests and returns a refusal, regardless of what's in the documents.
- **"Does X exist?" trick questions get caught** — the same file detects when a question has an unreliable premise (asking about something that doesn't exist in the corpus) and returns an honest "not found" rather than answering around it.
- **The vector schema is locked to a single version** ("3") across every cooperating service in the company's stack, so a version mismatch would fail loudly at startup rather than silently serving evidence built to a different, incompatible format.
- **Production configuration is self-enforcing**: [`app/config.py`](../app/config.py) refuses to start in production mode unless HTTPS is forced, the API docs endpoint is disabled, and the internal API key meets a minimum strength — misconfiguration is a startup crash, not a runtime surprise.

---

## 5. Defense in depth: why data can't leak between customers/projects

Because this service can hold data for multiple projects/departments in the same infrastructure, several *independent* layers all have to agree before any evidence is returned:

1. Only the trusted backend can call this service at all (an internal bearer credential is required and checked with constant-time comparison).
2. Each project gets its own physically separate vector-database collection, and the service verifies at query time that it actually got the collection it asked for.
3. Every vector search is filtered by the caller's authorized project/policy IDs *inside* the database query itself, not as an afterthought.
4. Every individual candidate passage is checked again against the caller's policy after retrieval.
5. The automated test suites measure cross-project and cross-department leakage directly and require it to be exactly zero on every run.

If any one of these layers had a bug, the others would still need to fail too before a leak could happen — which is what "defense in depth" means in practice, not just in principle.

---

## 6. Observability: watching a production system without spying on its content

Two systems track what's happening in production without ever capturing the actual questions or answers by default (see [`app/telemetry.py`](../app/telemetry.py), [`app/openinference_tracing.py`](../app/openinference_tracing.py)):

- **Metrics** (Prometheus-style counters/histograms): how many requests hit each pipeline stage, how long each stage took, how many tokens were used, how many retries happened — all labeled by stage/outcome/model, never by question or document text.
- **Tracing** (OpenInference/OpenTelemetry, viewable in a tool called Phoenix): a detailed timeline of each request's path through the pipeline, tagged with which authorization boundary it belongs to, so operators can debug a specific slow or failed request without that debugging capability becoming a way to casually browse private content.

This "content-free by default" design means the people operating the system can answer "is it healthy, is it fast, is it being used correctly" without needing to read what anyone actually asked.

---

## 7. Glossary (for readers completely new to this space)

| Term | Plain-English definition |
|---|---|
| **RAG (Retrieval-Augmented Generation)** | Searching your own documents first, then having an AI model answer using only what was found, instead of the model answering from memory. |
| **Embedding** | A list of numbers representing the *meaning* of a piece of text, produced by an AI model, used to find similar passages by meaning rather than exact wording. |
| **Vector database** | A database (here, Chroma) built to store and quickly search embeddings. |
| **Hallucination** | When an AI model states something confidently that isn't actually true or isn't backed by any source — the central risk RAG is designed to reduce. |
| **Grounding** | Verifying that a specific claim in an answer is actually supported by the evidence it cites. |
| **Cross-encoder / re-ranker** | A more accurate (but slower) model that scores exactly how relevant a passage is to a specific question, used as a second pass after a faster initial search. |
| **Fail-closed** | A design principle where, if something is uncertain or broken, the system refuses/denies rather than guessing or defaulting to "allow." |
| **Gold suite** | A hand-verified set of test questions with known-correct answers/evidence, used to measure system quality automatically. |
| **Leakage (cross-project/department)** | A customer, project, or department's data incorrectly appearing in another's results — a serious failure in any multi-tenant system. |

---

## 8. Where to look next

- Full architectural detail and diagrams: [`docs/CURRENT_ARCHITECTURE.md`](../docs/CURRENT_ARCHITECTURE.md)
- Full, current, evidence-backed quality numbers: [`docs/QUALITY_STATUS.md`](../docs/QUALITY_STATUS.md)
- How to run the evaluation suites yourself: [`evaluation/README.md`](../evaluation/README.md)
- Dependency and versioning rules: [`docs/DEPENDENCY_POLICY.md`](../docs/DEPENDENCY_POLICY.md)
