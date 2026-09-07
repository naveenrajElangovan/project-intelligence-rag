# Implementation prompt — one ordered pass: fix the open defect, then cut latency without touching quality

Repo: `~/Desktop/project-intelligence-rag`.

Work the six steps **in the order given**. Each step is self-contained: root cause, the exact change,
the test that proves it, and what to do if the proof fails. Do not reorder, do not batch, do not skip
a proof. Step 6 is the only step you are permitted to abandon, and §8 says when.

Background reading, not instructions: `RAG_FIX_AND_EVALUATION_PLAN.md` (items 2a–2i and the
evaluation layers) stays valid for everything this document does not cover — §9 lists what is still
open there. `RAG_LATENCY_PLAN.md` is superseded in full; three of its claims were wrong and the
corrected versions are Steps 3, 5 and 6 below.

---

## 0. Verified state of the repo — checked twice, second pass immediately before this document

| check | result |
|---|---|
| `git log --oneline -3` | `f9e3160` Align bilingual store assistant question routes · `f9b6f45` Restore department-scoped corpus and catalog releases · `f9d5ecd` Make pairwise and threshold calibration runs reproducible |
| `git status --porcelain \| wc -l` | `0` — tree clean |
| `git stash list` | `stash@{0}: --all-department-implementation` retained |
| `wc -l app/workflow.py` | **445** — `tests/test_architecture.py:17` caps it at 450 |
| `grep -rn "context_relevance_floor" app/ tests/` | **0 — no latency work has landed** |
| `grep -rn "LEADING_FRAGMENT" app/ tests/` | **0 — the follow-up defect is not fixed** |
| `app/config.py:24` | `supported_schema_versions = ("4", "3")` |
| last reported suite | **740 tests, zero failures** |

Sizes of every file this document touches: `workflow.py` 445 · `workflow_nodes/retrieval.py` 1490 ·
`workflow_nodes/answering.py` 2675 · `workflow_support/conversation.py` 558 · `llm.py` 1616 ·
`main.py` 538 · `config.py` 497 · `accelerator.py` 159. Only `workflow.py` has a line ceiling.

**The one open functional defect, reproduced on both passes:**

```
FOLLOW-UPS (must be True)
  FAIL  False  EXPLICIT_SUBJECT     "from the product types"
  ok    True   FOLLOWUP_PREFIX      "tell me more" / "dime mas" / "and the other app?"
  ok    True   ANAPHORIC_PRONOUN    "what is MC,MP here" / "que es MC, MP aqui"
STANDALONE (must be False)
  ok    False  EXPLICIT_SUBJECT     "is there a flow for reprints"
  ok    False  EXPLICIT_SUBJECT     "price check flow for leche"
  ok    False  EXPLICIT_SUBJECT     "what is the price check flow"
```

Everything else from the earlier rounds is present and working: the routing fix, the answer-relevance
gate, the bilingual lexicons, the language resolver and autocorrector, conversation anchor terms, the
pairwise judge harness.

**Latency baseline** — one full stage trace of a `NO_ANSWER / UNVERIFIED_EVIDENCE` request:
`plan_queries` 4.91s · `retrieve` 4.77s · `rerank` 3.45s · `evidence_completeness` 0.001s ·
repair retrieve 0.18s · repair rerank 0.69s · `generate` 14.37s · `citation_repair` 6.56s ·
`verify_grounding` 0.001s · `generate_safe_response` 2.76s · **total 37.79s**. Four serialised LLM
calls are 28.6s of that — 76%. Every deterministic gate combined is under 10 ms.

**The rule governing Steps 2–6: the computation that produces an answer must be unchanged. Only
wasted or serialised work is removed.** No threshold that judges truth moves. If a step cannot satisfy
its stated proof, revert that step — never relax the proof.

---

# STEP 1 — Fix the follow-up defect: a preposition-initial turn is a continuation

**Why first:** it is the only user-facing defect left. The rest of this document is optimization.

**File:** `app/workflow_support/conversation.py`

### Root cause

In `_conversation_resolution_decision`, the multiword rule:

```python
        if len(topic_words) >= 2 and not words & pronouns:
            return False, "EXPLICIT_SUBJECT"
```

`"from the product types"` normalises to `{from, the, product, types}`. The topic-word subtraction set
contains `for`, `of`, `to` but **not** `from`, so `topic_words` is `{from, product, types}` — three
words, no pronoun — and the turn is declared a self-contained new topic. The conversation is dropped,
retrieval runs on a bare noun fragment, and the live trace shows the result: one document at relevance
0.111, answer relevance 0.0249, refusal.

The general fact the code is missing: **a turn that opens with a bare preposition has no predicate of
its own.** It is the tail of the question already asked. Counting its nouns says nothing about whether
it introduces a new subject.

### The change

Insert this block **immediately before** the `topic_words = words - pronouns - {` assignment, so it
runs ahead of the multiword rule:

```python
    # A turn that opens with a bare preposition carries the previous
    # predicate: "from the product types" is the tail of the question already
    # asked, not a new one. The topic-word test below counts "product" and
    # "types" as two fresh subjects and returns EXPLICIT_SUBJECT, which drops
    # the conversation and retrieves on a fragment no document answers.
    # Bounded to short fragments that carry no interrogative and no finite verb
    # of their own, so "from the product types, what is MC?" and "de acuerdo
    # con la politica, cual es el limite?" stay standalone.
    leading = _normalized_words(normalized)[:1]
    if (
        leading
        and leading[0] in _CONTINUATION_LEADING_WORDS
        and len(normalized.split()) <= _MAX_CONTINUATION_FRAGMENT_WORDS
        and not words & _INDEPENDENT_PREDICATE_WORDS
    ):
        return True, "LEADING_FRAGMENT_CONTINUATION"
```

Add these constants immediately **above** the existing
`# Shared with the follow-up predicate so the two cannot drift apart.` comment:

```python
# A question fragment that begins with one of these has no predicate of its own.
_CONTINUATION_LEADING_WORDS = frozenset({
    "from", "for", "about", "with", "within", "under", "regarding", "concerning",
    "de", "del", "para", "por", "sobre", "con", "desde", "segun", "respecto",
    "acerca",
})

# An interrogative or finite verb makes a fragment a question in its own right,
# whatever preposition opens it. Accent-stripped: _normalized_words folds
# diacritics, so "cual" here also matches "cuál".
_INDEPENDENT_PREDICATE_WORDS = frozenset({
    "how", "what", "when", "where", "which", "who", "whom", "whose", "why",
    "am", "are", "be", "can", "could", "did", "do", "does", "had", "has",
    "have", "is", "may", "must", "should", "was", "were", "will", "would",
    "como", "cuando", "cual", "cuales", "donde", "que", "quien", "quienes",
    "es", "son", "esta", "estan", "estuvo", "fue", "fueron", "hace", "hacen",
    "hay", "podria", "puede", "pueden", "sera", "seran", "tiene", "tienen",
})

_MAX_CONTINUATION_FRAGMENT_WORDS = 6
```

Three properties keep this narrow rather than a heuristic land-grab:

1. **Bilingual by construction** — English and Spanish prepositions live in the same set, so
   `"de los tipos de producto"` behaves identically to the English. `_normalized_words` strips
   diacritics, so `según`/`segun` and `cuál`/`cual` need no separate entries.
2. **A predicate of its own wins.** Any interrogative or finite verb anywhere in the turn disables the
   rule, so `"from the product types, what is MC?"` and
   `"de acuerdo con la politica de compras, ¿cuál es el límite?"` stay standalone.
3. **Bounded to 6 words.** `"sobre el flujo de precios de leche en las tiendas 3B"` carries enough
   subject of its own for retrieval and keeps the existing behaviour.

**Naming constraint — this is not cosmetic.** `tests/test_corpus_agnostic_gate.py` scans every file
under `app/` for the raw uppercase substrings `POS` and `BOT` and fails on any hit. `PREPOSITIONAL`
and `PREPOSITIONS` both contain `POS`, so no identifier or emitted value may use those words. Hence
`_CONTINUATION_LEADING_WORDS`, `_MAX_CONTINUATION_FRAGMENT_WORDS` and the reason code
`LEADING_FRAGMENT_CONTINUATION`. Do **not** satisfy that guard by splitting a literal
(`"PREPO" + "SITIONAL_CONTINUATION"`) — that defeats a scanner whose whole value is that it cannot be
talked around, and it leaves a corpus token in telemetry. Rename instead.

Nothing downstream needs changing. `_conversation_context_subject` already does the right thing once
`is_followup` is `True`: `_conversation_subject("from the product types")` yields `"product types"`,
that fails the vocabulary match, `explicit` is cleared, and the carried subject is used.
`conversation_anchor_terms` already returns `("BOTFLOW-110",)` for this exact question — there is a
passing test for it
(`tests/test_conversation_anchoring.py::test_a_section_anchor_survives_a_question_with_no_identifiers`).
The identifiers were always ready; only the classifier refused to ask for them.

### New test file — `tests/test_prepositional_continuation.py`

```python
"""A turn opening with a bare preposition has no predicate of its own."""

import pytest

from app.workflow_support.conversation import _conversation_resolution_decision

VOCABULARY = ("pos", "bot", "iot")


@pytest.mark.parametrize(
    "question",
    (
        "from the product types",
        "de los tipos de producto",
        "para el flujo de precios",
        "about the reprints",
        "sobre las reimpresiones",
        "for leche",
        "con el departamento de finanzas",
        "según el manual de compras",
        "From the product types.",
        "¿de los tipos de producto?",
    ),
)
def test_a_preposition_initial_fragment_continues_the_previous_turn(question: str) -> None:
    assert _conversation_resolution_decision(question, VOCABULARY)[0] is True


@pytest.mark.parametrize(
    "question",
    (
        "from the product types, what is MC?",
        "de acuerdo con la politica de compras, cual es el limite?",
        "for the price check flow what does the POS require",
        "sobre el flujo de precios de leche en las tiendas 3B",
    ),
)
def test_a_fragment_with_its_own_predicate_stays_standalone(question: str) -> None:
    assert _conversation_resolution_decision(question, VOCABULARY)[0] is False


def test_the_reason_code_is_content_free() -> None:
    assert _conversation_resolution_decision("from the product types", VOCABULARY)[1] == (
        "LEADING_FRAGMENT_CONTINUATION"
    )
```

If `tests/test_telemetry_privacy.py` enumerates reason codes, add `"LEADING_FRAGMENT_CONTINUATION"` to
that list.

### Required proof — the old-vs-new decision diff

This rule was prototyped against copies of the real module and diffed decision-by-decision against
the unpatched module. Reproduce that before committing. `conversation.py` depends only on
`language.fold` and `query_analysis._normalized_words`, so this needs no venv:

1. Copy `app/workflow_support/{conversation,language}.py` into two scratch package trees, stub
   `query_analysis` with just `_normalized_words`, patch one copy.
2. Run each question in the corpus through `_conversation_resolution_decision` under three
   vocabularies: `None`, `("pos","bot","iot")`, `("checkout","inventory")`. One case = one
   (question, vocabulary) pair.

**The acceptance criterion is structural, not a bare number — the count depends on which corpus you
assemble, and an earlier draft of this document quoted a count without pinning the corpus. Three
conditions, all corpus-independent:**

1. **Every changed decision is a preposition-initial fragment** — first token in
   `_CONTINUATION_LEADING_WORDS`, at most 6 words, no word from `_INDEPENDENT_PREDICATE_WORDS`.
2. **Every change moves in one direction only**: `False → True`, or an already-`True` case whose
   reason code becomes the more precise `LEADING_FRAGMENT_CONTINUATION`. A `True → False` change anywhere
   means the rule is wrong.
3. **Zero decisions change** among the question literals that appear in `tests/test_followup_detection.py`,
   `tests/test_elliptical_followup.py` and `tests/test_conversation_anchoring.py`, and zero change
   among the four negative cases in `tests/test_prepositional_continuation.py`.

Two corpora were actually measured, so you can check your harness against either:

| corpus | questions | cases | changed |
|---|---|---|---|
| every literal from the three existing test files + the seven core prepositional fragments | 68 | 204 | **21** |
| the same, plus all 10 positives and 4 negatives from `tests/test_prepositional_continuation.py` | 72 | 216 | **30** |

The 9-change difference is `según el manual de compras`, `From the product types.` and
`¿de los tipos de producto?` × 3 vocabularies — three positives that live only in the new test file.
Both results satisfy the three conditions above, which is the point: **use the second corpus (72
questions, 216 cases, 30 changes) since it covers every literal you are shipping a test for.**

A change that fails any of the three conditions means the rule is wrong. Stop and investigate; do not
adjust the expectation.

---

# STEP 2 — A4: template the refusals instead of generating them

**Saving: ~2.8s on every refusal, and it removes an LLM call from the failure path.**
**Why second:** smallest surface, no invariant to establish, and it *reduces* `workflow.py`, which is
at 445 of its 450-line ceiling — do this before anything else touches that file.

**Files:** `app/llm.py`, `app/workflow.py`, `app/config.py`

### What is there now

`app/workflow.py`, in the `generate_safe_response` stage, constructs
`LangChainSafeResponseGenerator(...)` and awaits `responder.generate(question, language, refusal_reason)`
to have the model write prose such as "we could not confirm the specific details". That generator's
`reason` parameter is a `Literal` of exactly **12 reason codes**: `NO_ACCESS`,
`INSUFFICIENT_EVIDENCE`, `UNVERIFIED_EVIDENCE`, `POPULATION_RETRIEVAL_MISS`,
`UNRESOLVED_SOURCE_CONFLICT`, `SOURCE_SCOPE_VIOLATION`, `PERMISSIONS_NOT_SATISFIED`,
`FRESHNESS_NOT_VERIFIABLE`, `REQUESTED_COVERAGE_INCOMPLETE`, `UNSUPPORTED_CLAIM`,
`INVALID_DERIVATION`, `TEMPORARILY_UNAVAILABLE`. With two languages that is 24 fixed strings.

### The change

The pattern already exists in `app/llm.py`: `no_access_answer(language)`,
`insufficient_evidence_answer(language)` and `pipeline_unavailable_answer(language)` sit beside their
`*_ES` constants. Extend it:

```python
def refusal_answer(reason: str, language: str) -> str:
    """Deterministic user-facing refusal per (reason_code, language)."""
```

with an explicit mapping covering all 12 codes in both languages, falling back to
`insufficient_evidence_answer(language)` for an unrecognised code. In `workflow.py`, replace the
generator call with `refusal_answer(refusal_reason, language)` and set
`reason_code = f"TEMPLATED_{refusal_reason}"`.

Add `generated_refusals_enabled: bool = False` to `Settings` and keep the LLM path reachable behind
it, so the change is reversible by env var and the existing generator and its tests stay live.

Leave the `ENTITY_MISMATCH` branch exactly as it is — it is already deterministic and must keep
producing "Did you mean …?" / "¿Quisiste decir …?".

### Why this is not a quality change

Refusal wording carries no claim, no evidence and nothing for grounding to verify. It is also better
on its own terms: `PARTIAL_GROUNDING_2026-08-22.md` records that the model-written refusal wording
needed to be firmer, which a fixed string fixes permanently.

### Tests

Every one of the 12 reason codes returns non-empty text, distinct per reason, in both languages; no
template contains a project name, document title, identifier or the user's question; `ENTITY_MISMATCH`
still produces the clarification rather than a template.

---

# STEP 3 — A2: skip a repair pass that provably cannot change anything

**Saving: ~0.9s — and it may fire rarely. Ship it anyway; it is cheap and correct.**

**Files:** `app/workflow_nodes/answering.py`, `app/workflow_nodes/retrieval.py`

### Correcting the earlier claim

`RAG_LATENCY_PLAN.md` proposed skipping the repair scoring pass whenever the candidate set was
unchanged. That is not safe. `_repair_completeness` (the node logging `BOUNDED_RETRIEVAL_REPAIR`) sets
`queries` to a **new** `_completeness_repair_query(...)`. A different query means different
cross-encoder pairs, so the rerank result is not guaranteed identical, and the existing
`app/reranking.py::cached_scores` pair cache cannot serve it. The identical relevance seen in both
traces (0.009 → 0.009, 0.111 → 0.111) is an observation, not a guarantee.

### The change

Skip the second scoring pass **if and only if** both hold:

- the repair query is byte-identical to a query already retrieved on, **and**
- the candidate id set is unchanged.

Identical inputs to a deterministic scorer cannot produce a different output — that is the entire
safety argument. Implement it as that conjunction. Do **not** implement a relevance-delta check: a
relevance comparison is a guess about the future, not a proof about the present.

### Test

A fake retriever/scorer recording call counts: assert the second scoring pass is skipped on identical
`(query, candidate ids)` and **executed** when either differs.

---

# STEP 4 — A1: do not generate from evidence that has exhausted repair and scored as noise

**Saving: ~21s on hopeless refusals — `generate` 14.4s plus `citation_repair` 6.6s. The largest
Group A win.**

**Files:** `app/config.py`, `app/workflow_nodes/retrieval.py`
**Prerequisite:** a Layer 1 run, before you write any code. This is not a formality — the floor's
correctness guarantee comes from that run's data.

### What the trace showed

The pipeline generated an answer from a pool at `context_relevance = 0.009`, spent 6.6s repairing its
citations, and grounding then rejected every claim. 0.009 is noise, not a borderline signal.

### Do not reuse `context_relevance_threshold` (0.25)

That is a different gate. It is passed as `relevance_threshold` to the heuristic context evaluator in
`_validate_evidence_completeness` (the `self._context_evaluator.evaluate(...)` call) and decides
whether the pool is *incomplete and worth repairing*. Step 4 needs a separate, far lower
**termination** floor.

### Derive the floor from data — do not pick a number

```bash
python -m evaluation.run_retrieval_eval --project-id <PROJECT> \
  --out .run/layer1.jsonl --generate <ALL>

python - <<'PY'
import json, pathlib
rows = [json.loads(line) for line in
        pathlib.Path(".run/layer1.generation.jsonl").read_text().splitlines() if line]
ok = [r["context_relevance"] for r in rows
      if r.get("answered") and r.get("grounding_accepted")
      and r.get("context_relevance") is not None]
print("successful cases:", len(ok), "min context_relevance:", min(ok))
PY
```

The generation lane already writes `context_relevance`, `answered` and `grounding_accepted` per row —
no instrumentation needed. Set the floor **strictly below** that observed minimum (round down: minimum
0.085 → floor 0.05) and record the derivation in the config comment.

### The change

In `_route_after_evidence_completeness` (`app/workflow_nodes/retrieval.py`), on the **exhausted**
branch only — the final `return "generate" if state.get("documents") else "end"`, reached after
`retrieval_attempt >= max_retrieval_attempts`:

```python
        if float(state.get("context_relevance") or 0.0) < self._settings.context_relevance_floor:
            return "end"
        return "generate" if state.get("documents") else "end"
```

**This placement is what makes the guarantee tight.** The repair pass still runs. The floor only ever
sees a pool that has already been through repair — exactly the pool whose `context_relevance` the eval
rows record. So the floor sits below every relevance value that ever produced a grounded, answered
outcome, and by construction cannot change an outcome that previously succeeded. The genuine
borderline cases in the traces (0.191, 0.111) stay far above it and still reach generation, so the
earlier routing fix keeps working. Below the floor nothing is generated, so `citation_repair` is never
reached — no separate change for it.

In `app/config.py`, beside `context_relevance_threshold`:

```python
    # Termination floor, NOT the repair-worthiness threshold above. Derived from a
    # Layer 1 run: strictly below the minimum context_relevance that ever produced
    # an answered, grounded outcome (<RUN ID>, minimum <VALUE>). It therefore cannot
    # change an outcome that previously succeeded. Raising it above that minimum
    # would make it a truth gate, which grounding — not a rerank score — decides.
    context_relevance_floor: float = <DERIVED>
```

Validate it in `Settings`: reject `context_relevance_floor >= context_relevance_threshold` and
anything outside `0 <= x <= 1`, so no future edit can quietly promote it into a truth gate.

### Tests

A routing unit test with two states — one just under the floor with documents present → `"end"`, one
just over → `"generate"` — plus a test asserting the validator rejects a floor at or above
`context_relevance_threshold`.

---

# STEP 5 — A5: let requests overlap where they do not contend

**Throughput, not per-request latency — and for a rollout across finance, compras and logistics this
is probably your real constraint.** With 38-second requests the second concurrent user waits 76
seconds and the third 114.

**Files:** `app/accelerator.py`, `app/config.py`, `app/main.py`
**The two sub-steps must not be reordered.**

### 5a — bound the accelerator first

`app/accelerator.py` has **no** concurrency guard today. Raising admission before adding one would
send concurrent embed/rerank calls into a single MPS process. Add
`accelerator_max_concurrency: int = 1` to `Settings` and gate the accelerator HTTP calls on it. This
is what keeps unified-memory use flat while HTTP admission rises.

### 5b — then decouple admission from the model slot

`app/main.py::_acquire_request_slot` computes
`capacity = min(settings.max_inflight_requests, settings.local_max_concurrency)` when local inference
is enabled, and logs *"Admission capacity is 1, clamped from PI_RAG_MAX_INFLIGHT_REQUESTS=4 by
PI_RAG_LOCAL_MAX_CONCURRENCY=1."*

The model slot is already acquired per LLM call, not per request (`_model_slot` in `app/llm.py` takes
`_local_semaphore(settings.local_max_concurrency)`), so generation stays serialised whatever admission
does. Raising admission lets request B retrieve and rerank while request A generates — identical
computation per request, only overlap changes.

Add `admission_capacity_override: int | None = None`, used in place of the `min(...)` when set, with
the existing clamp as the default. The startup log line must state which path is active. Do not delete
the clamp.

### Then verify headroom

Check MPS memory under two concurrent requests before raising it further. The failure mode is
out-of-memory — an **availability** risk, not a quality one — and the accelerator refuses CPU fallback
by design, so an OOM is a hard failure, not a slow one.

### Test

With `local_inference_enabled=True`, `max_inflight_requests=4`, `local_max_concurrency=1` and the
override set: admission admits 4 while `_model_slot` still serialises to 1. With the override unset:
behaviour byte-identical to today.

---

# STEP 6 — A3: overlap translation with first-pass retrieval

**Saving: ~4.7s on English questions. Last, because it is the only step with a hard invariant — and
the only step you may abandon.**

**Files:** `app/workflow_nodes/planning.py`, `app/workflow_nodes/retrieval.py`

### What is there now

In `app/workflow_nodes/planning.py`, the branch guarded by
`if detected_language in ("es", "en") and self._settings.translation_enabled:` awaits
`planner.translate_to_english(question)` / `planner.translate_to_spanish(question)` and appends the
result to `queries` **before** `retrieve` starts. Retrieval waits 4.9s for a query variant it could
have been working alongside.

### Why the naive version is not safe

`_retrieve` fuses queries with RRF and records `query_candidate_ranks` keyed by
`str(query_indexes[query])` — the query's **index in `state["queries"]`** — and sets
`primary_query_rank` when `query == resolved_question`. Downstream selection reads those keys (see
`tests/test_primary_query_candidate_preservation.py`). Splitting retrieval into two passes without
care renumbers that metadata and changes what survives.

### The safe implementation

- Pre-allocate the translated variant's slot in `state["queries"]` **before** dispatching, so its
  query index is the same integer it has on the serial path.
- Start the translation call and the dense retrieval of the untranslated queries concurrently
  (`asyncio.gather`), await the translation, then issue **only** the additional
  `(translated_query × scopes)` requests and merge them into the same `unique` dict.
- **Always** issue that second retrieval. Never make it conditional on the first pass looking weak —
  that changes the candidate pool and forfeits the guarantee. (§8 already rejects skipping translation
  on lexical grounds; this is the same trap wearing a stopwatch.)
- The invariant holds because RRF is a sum, so merge order does not matter;
  `existing.metadata["score"]` is a `max`, likewise; `query_candidate_ranks` is preserved by the
  pre-allocated index; `primary_query_rank` depends only on `query == resolved_question`; the
  `preserve_candidates` path is untouched.

### Required proof — an equality test, not a benchmark

With a fake retriever returning fixed documents per query, run the serial path and the overlapped path
and assert **byte-identical** output: the ordered candidate list, and per candidate
`retrieval_rrf_score`, `query_candidate_ranks`, `primary_query_rank` and `score`. Also assert the
translated query is still issued when the first pass is strong, and that `_safe_translation_variant`
still gates it.

### If that test cannot be made to pass, revert Step 6 and ship Steps 1–5

It is 4.7s. The bilingual bridge is what fixed the `leche` case, and it is worth more than 4.7s.

---

# STEP 7 — Rebuild, then verify

**Editing files changes nothing until the images are rebuilt.** `api` and `rag` are Docker containers
started by `~/Desktop/project-intelligence-backend/scripts/prepare_and_start_local_app.sh`
(`docker compose up -d --build rag api`); only the MPS accelerator on `host.docker.internal:8004`
runs natively.

```bash
cd ~/Desktop/project-intelligence-backend && ./scripts/prepare_and_start_local_app.sh
```

### End-to-end conversation, through the mobile client, in this order

1. `"price-checking flow for a product"` → must answer (already works today).
2. `"what is MC,MP here"` → must answer, citing the source that defines the type codes.
3. `"from the product types"` → **must answer**; the trace must show
   `predicate_reason=LEADING_FRAGMENT_CONTINUATION` and a non-empty anchor-term list.
4. `"de los tipos de producto"` → the same, in Spanish.
5. In a **fresh** conversation, `"what is the price check flow"` → must still answer, and the trace
   must show `EXPLICIT_SUBJECT` — proving nothing inherited a subject that does not exist.

### Acceptance gate — all of it, or the change does not ship

- Full suite green. Baseline was **740 tests, zero failures**; the new files add to that count. Zero
  failures, and no test weakened, skipped, or given a `getattr` shim to make it pass.
- `wc -l app/workflow.py` ≤ 450. It is 445 today; Step 2 should reduce it.
- The Step 1 classifier diff shows exactly the 21 intended changes out of 204.
- The Step 6 equality test asserts byte-identical candidate metadata, or Step 6 is reverted.
- Layer 1 before and after the whole batch: no regression in `recall_at_k`, `ndcg_at_k`, gold
  resolution (100%) or leakage (0), in **either** language, and no widening of the language gap.
- A re-traced hopeless refusal is measurably faster, and a case that previously answered still answers
  in the same confidence band.

### Expected result

| path | before | predicted | **measured at `ffebae8`** |
|---|---|---|---|
| refusal, the traced hopeless case | 37.79s | ~11s | **27.13s** |
| refusal, evidence below the derived floor | 37.79s | ~11s | not yet observed |
| answered, English | ~35s | ~30s | to measure |
| answered, Spanish | ~30s | ~30s | to measure |
| second concurrent user | +38s queued | overlapped | unchanged — override left unset |

**The ~11s prediction was wrong, and the reason matters more than the miss.** The Layer 1 derivation
returned a minimum answered-and-grounded `context_relevance` of **0.005** across 27 successful cases,
so the floor is 0.001 — while the traced refusal sat at 0.009. The floor cannot fire on it, and no
floor derived below 0.005 ever could. Grounded answers do sometimes come from near-noise relevance,
which means `context_relevance` is not separable in that range: **Step 4 buys nothing on the case it
was designed for.** The measured 10.7s saving is Steps 2, 3 and 6.

Two consequences. First, do not quote ~21s for Step 4 anywhere; the honest figure is ~0s until a
signal that actually separates hopeless pools from borderline ones is found. Second, that 27-case,
0.005-minimum distribution is worth inspecting on its own — a floor pinned by one outlier says more
about the metric than about the evidence.

**Report this table honestly: these steps fix refusals and barely touch answered requests.** The 14.4s
generation plus 8.2s retrieve-and-rerank is a floor, and none of it is waste — it is the work that
produces a grounded answer. Perceived latency equals total latency by design
(`app/workflow_support/streaming.py::verified_answer_events` chunks an already-verified answer), and
that design is correct; there is no free perceptual win to take.

---

## 8. Not in this sequence — and why

### Blocked, not rejected: the only remaining large win

Making **answered** requests meaningfully faster means changing what the model sees or which model
sees it. That is conditional on proof, and the proof harness is currently broken: **the pairwise
judging run timed out and RAGAS is blocked.** Fix the pairwise timeout first; without Layer 4 there is
nothing to ship these on.

- **B1 — a quantised build of the same generator model.** Decode is ~10–14 tok/s estimated from a
  single sample, slow for this hardware. A q4/q5 build typically gives 2–3× decode, taking `generate`
  from ~14.4s toward ~6–7s on **every answered request**. Gate: pairwise judge across the swap;
  ship only on `verdict_reliability: OK` with no significant candidate loss.
- **B2 — `PI_RAG_RERANK_TOP_N` 16 → 8** (8 is the code default; the env doubles it). Newly worth
  measuring because there is now a real baseline: **`nDCG@16 = 0.3790`, `Recall@25 = 0.6681`** —
  stable but weak in absolute terms, so the 16th document is not obviously carrying its cost. Gate:
  Layer 1 before and after, both languages. Note `evaluation/score.py` derives `k` from
  `rerank_top_n`, so this renames your dashboard series — plan for the discontinuity.
- **B3 — confirm `answer_detail`.** It is `"standard"` in `config.py`; confirm the deployed env is not
  overriding it to `"detailed"`, which widens every sentence band and scales decode with it. Reading
  the value costs nothing; changing it needs the pairwise judge.

**Cheap prerequisite, worth doing alongside:** per-stage p50/p95 panels split by outcome in
`grafana/dashboards/rag-retrieval-and-tokens.json`. `duration_ms` per stage is already emitted and
already scraped — this is a dashboard change, not instrumentation. Record output token counts beside
`prose_stream_seconds` so tokens/second is measured rather than estimated. Timing a Layer 1 run gives
a full latency distribution in one command, and it is the same run Step 4's floor comes from.

### Rejected outright — do not let these back in

- Lowering `grounding_score_threshold`, `answer_relevance_threshold`, or `context_relevance_floor`
  beyond its derived value. These are correctness gates; a faster wrong answer is strictly worse than
  a slow refusal.
- Cutting `max_evidence_tokens`. Prefill is 3.9s of 14.4s — decode is the bottleneck. Costs recall for
  almost no speed.
- Removing the answer-relevance gate. One cross-encoder pair, tens of milliseconds, and it is what
  stops a confident irrelevant answer reaching a user.
- Undoing the routing fix. Step 4 reaches the same latency while keeping the behaviour that lets
  genuine borderline evidence produce an answer.
- Skipping translation when lexical recall looks adequate. Step 6 removes its latency without touching
  its behaviour.
- Streaming unverified deltas to the client. The largest perceived win available, and exactly the
  trade the governing rule forbids.

---

## 9. Still open elsewhere — not latency, not superseded

From `RAG_FIX_AND_EVALUATION_PLAN.md`, unchanged:

- **2b-ter** — the four observations from the live traces that were never examined.
- **2e** — threshold calibration (`evaluation/calibrate_threshold.py`) against the real distribution.
- **2f** — the `coverage_missing` decision.
- **2h** — verify the ingress distributed rate limiter. RAG's in-process limiter is a documented
  backstop ("ingress remains the distributed limiter"), so this is a verification task, not a gap.
- **Layer 3** — RAGAS over the 60 reviewed references (blocked).
- **Layer 5** — the generator absent from the stash; recreate or confirm dropped.
- **Live `PI_RAG_SUPPORTED_SCHEMA_VERSIONS`** — the code is `("4", "3")`; confirm the deployed
  environment matches, or a schema-4 namespace meets a schema-3 reader and returns 409.
- The catalog download endpoint has **no implementation**, so its SHA-256 verification is
  unimplemented. An earlier claim to the contrary was retracted and stays retracted.

---

## 10. What this document does not claim

The Step 2–6 savings derive from **one** stage trace, not a p50 or p95 — the dashboard work in §8 is
what turns them into measurements. Step 4's floor is provably outcome-preserving *for the outcomes the
eval run recorded*; a case that would have crossed the floor only after a repair pass the eval never
exercised falls outside that guarantee, which is exactly why the floor sits on the exhausted branch
and strictly below the observed minimum. Everything in §8 is unproven by construction and must stay
behind its gates. Step 1 is tested at the classifier level with a 204-case regression diff, and its
end-to-end behaviour is proven by the five-step conversation in Step 7 — not by assumption.
