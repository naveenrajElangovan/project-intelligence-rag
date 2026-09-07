# Implementation prompt — make the two personas work: developer (`T2.0`) and store user (`T2.0-STORE`)

Repos: `~/Desktop/project-intelligence-rag`, `~/Desktop/project-intelligence-backend`,
`~/Desktop/project-intelligence-mobile`.

Work the five steps **in the order given**. Each is self-contained: root cause, the exact change, the
test that proves it, and what to do if the proof fails. Steps 1–3 are RAG and are the whole of the
"store user gets refused / gets asked a nonsense question" report. Step 4 is the "wrong corpus after
switching accounts" report and touches the backend and the client. Step 5 is the measurement gap that
made all of this invisible.

Do not reorder. Do not relax a proof. Nothing here moves a truth threshold: every change either stops
the pipeline routing to a source family the project does not have, or stops it asking a question that
has no second answer in that project.

---

## 0. Verified state — inspected directly on 2026-09-07

| check | result |
|---|---|
| RAG `git log --oneline -1` | `d21b29d` Rename leading fragment continuation telemetry |
| RAG `git status --porcelain` | 1 entry — untracked `docs/34_FINAL_FIX_AND_LATENCY_PROMPT_2026-09-07.md` |
| RAG stash | `stash@{0}: --all-department-implementation` still retained |
| backend `git status` | 14 modified, 4 untracked — includes **both** `config/local-project.T2.0.json` and `config/local-project.T2.0-STORE.json` |
| mobile `git status` | 4 changed — `ExampleIdentityGateway` now forces `Prompt.SELECT_ACCOUNT` |
| `wc -l app/workflow_support/query_analysis.py` | 827 |
| `wc -l app/workflow_support/fail_closed.py` | 317 |
| `wc -l app/workflow.py` | 444 — `tests/test_architecture.py:17` caps it at 450 |
| RAG test files | 73 |

### What changed since the store corpus landed

| commit | what it did | consequence for the store persona |
|---|---|---|
| `f9b6f45` | Restored department/role scoping (`authorized_project_policies`), added `catalog_answers.py`, added the whole `docs/store-assistant/` pack and `corpora/T3B-COMPANY/` | Isolation is correct. `catalog_answers.py` is hard-gated to `project_id == "T3B-COMPANY"` and never fires for `T2.0-STORE`. |
| `f9e3160` | Aligned the bilingual canonical question index | Documentation only. |
| `30c0cba` | Recognised preposition-initial turns as continuations | **Regression** — see Step 3. |
| `b413db2` … `d21b29d` | Latency steps 2–6 (templated refusals, repair-rerank skip, relevance floor, admission, translation overlap) | No persona effect found. |

### The two corpora — isolation is not the problem

`T2.0` (Confluence + Jira + two GitHub repos) and `T2.0-STORE` (one Confluence space, 23 root pages,
no Jira, no GitHub) share the logical collection `project-intelligence` and are written into **separate
physical Chroma collections** by `app/chroma_collections.py::project_collection_name`
(`project-intelligence-<slug>-<sha256[:12]>`), each carrying `project_id` and `logical_collection`
metadata that `verify_project_collection` re-checks on every read. Every chunk also carries
`access_policy_id = project:<id>`, filtered server-side by `_authorized_policy_filter`. Two independent
boundaries. **Nothing below is a leak; every defect is the pipeline refusing to use the corpus the user
is entitled to.**

---

# STEP 1 — Never route a question to a source family the project's corpus does not contain

**This is the "store user gets refused on answerable questions" report, and most of the Spanish gap.**

**File:** `app/workflow_support/query_analysis.py`

### Root cause

`_source_route_intent(question, available_source_types)` already receives the project's observed
vocabulary — `planning.py:238`, `:453` and `:611` all pass `self._vocabulary.source_types`, built by
ingestion from the metadata actually written (`app/vector.py::_observed_vocabulary`, key
`source_types`). For `T2.0-STORE` that value is `("PAGE",)`.

The function consults it in exactly one place — the `CROSS_SOURCE` branch at line 515. Every
`DELIVERY` return (lines 473, 503, 505) fires unconditionally. `_intent_source_scope("DELIVERY")` is
`(("ISSUE",), "JIRA")`, and `_required_evidence_source_types("DELIVERY")` is `("ISSUE",)`, so
`_validate_evidence_completeness` (`workflow_nodes/retrieval.py:1516`) appends `source:ISSUE` to
`missing`, the bounded repair loop cannot satisfy it, and the request refuses. The store project has no
issues and never will.

### Reproduced

Ten real store questions — two of them lifted verbatim from `docs/store-assistant/es/topics/` — run
through the live function with `available_source_types=("PAGE",)`:

```
DELIVERY       scope=('ISSUE',)         ¿Cómo hago entrega de valores?
DELIVERY       scope=('ISSUE',)         ¿Cómo filtro prioridad?
DELIVERY       scope=('ISSUE',)         ¿Dónde veo el estado del ticket?
DELIVERY       scope=('ISSUE',)         ¿Qué hago con los errores de la impresora?
DELIVERY       scope=('ISSUE',)         ¿Cómo registro la entrega de mercancía?
DELIVERY       scope=('ISSUE',)         What is the status of the delivery?
CODE_ASSISTED  scope=('PAGE', 'CODE')   ¿Cómo reimprimo un ticket?
CODE_ASSISTED  scope=('PAGE', 'CODE')   ¿Cómo cierro el turno?
CODE_ASSISTED  scope=('PAGE', 'CODE')   How do I hand over the cash?
CODE_ASSISTED  scope=('PAGE', 'CODE')   the printer shows an error
```

Six of ten refuse before an embedding is computed. The trigger words are `entrega`, `prioridad`,
`estado`, `errores`, `delivery`, `status` — which in a *store* are goods hand-over, label priority,
screen state and printer errors, and in Jira are none of those things. `¿Cómo hago entrega de
valores?` is a canonical question in the corpus the user is being refused from.

### The change

Compute the available set once, at the top of `_source_route_intent`, and make every `DELIVERY` return
conditional on it — the same shape the `CROSS_SOURCE` branch already uses:

```python
    source_types = {value.upper() for value in available_source_types}
    # A project with no issue tracker cannot have a delivery question. The words
    # that select DELIVERY -- entrega, prioridad, estado, error, ticket -- are
    # ordinary store vocabulary, so on a documentation-only corpus this branch
    # routed answerable questions to a source family with zero documents and the
    # evidence gate then refused them. An empty set means "vocabulary not yet
    # observed", which must keep today's behaviour.
    issue_sources_available = not source_types or "ISSUE" in source_types
```

Then guard each `DELIVERY` return with `issue_sources_available` and let the ladder fall through when
it is false. The Jira-key pattern at line 473 gets the same guard — `[SYNC-01]` appears in
`10_CANONICAL_QUESTION_INDEX.md` and matches `[A-Z][A-Z0-9]+-\d+`.

Do the same for the code family, in `planning.py` where `CODE_INVENTORY` is selected: a project whose
vocabulary has no `CODE` cannot answer a code inventory, and `_required_evidence_source_types` demands
`("CODE",)`.

**Then narrow the scope to what exists.** After `source_types, source_route = _intent_source_scope(...)`
in each of the three planning call sites, intersect with the project vocabulary, preserving order, and
**fall back to `()` (unscoped) rather than to an empty scope**:

```python
    if available:
        narrowed = tuple(t for t in source_types if t in available)
        source_types = narrowed or ()
```

Retrieval against a source type with no documents can only return nothing, so removing it cannot change
any result — that is the whole safety argument. It also removes the wasted `CODE` leg on every store
request.

### Test — `tests/test_source_family_availability.py`

- Each of the six DELIVERY-routed questions above returns a non-`DELIVERY` intent under
  `("PAGE",)`, and still returns `DELIVERY` under `("PAGE", "CODE", "ISSUE")`.
- `"show me the open jira issues"` under `("PAGE", "CODE", "ISSUE")` → `DELIVERY`; under `("PAGE",)` →
  not `DELIVERY`.
- `available_source_types=()` reproduces today's routing for every question in
  `tests/test_source_routing*.py` — **zero decisions change** when the vocabulary is unobserved.
- Scope narrowing: `("PAGE","CODE")` under a `("PAGE",)` vocabulary becomes `("PAGE",)`; under an empty
  vocabulary it is unchanged; an intersection that would be empty yields `()`.

### If it fails

If any existing routing test changes decision under an empty vocabulary, the guard is in the wrong
place — it must never alter the unobserved-vocabulary path. Fix the guard, do not edit the test.

---

# STEP 2 — Do not ask a user to disambiguate a sense their corpus does not contain

**This is half of "some are not responding cleanly".**

**File:** `app/workflow_support/fail_closed.py`

### Root cause

`clarification_response` runs **before** the graph (`workflow.py:187` and `:210`). Its first branch:
any question containing `ticket`/`tickets`/`boleto`/`boletos`, with no `delivery_context` word and no
`document_context` word, returns `NEEDS_CLARIFICATION` /
`AMBIGUOUS_SOURCE_FAMILY` — *"Do you mean a work item or a receipt/document?"*.

`ticket` occurs **71 times** in the Spanish store corpus, always meaning the printed receipt. The store
project has no work items at all, so the question it asks has no second answer.

The `document_context` list is also whole-word: `imprimir|reimprimir|impresora`. Spanish is conjugated,
so `imprime`, `imprimo`, `reimprimo`, `impresión` all miss.

### Reproduced

```
CLARIFY  ¿Por qué no imprime el ticket?
CLARIFY  No salió el ticket de tiempo aire.        <- verbatim from the ES corpus
CLARIFY  ¿Cómo cancelo un ticket?
CLARIFY  El ticket salió cortado
CLARIFY  ¿Puedo copiar un ticket?
CLARIFY  Why is the ticket blank?
CLARIFY  The ticket did not come out
CLARIFY  ¿Cómo reimprimo un ticket?                <- reimprimo != reimprimir
ok       ¿Dónde veo el estado del ticket?          <- the only genuinely ambiguous one, passes through
```

Eight of nine store receipt questions are answered with a disambiguation prompt. The one case that is
actually ambiguous is the one that gets through — and Step 1 shows where it then goes.

### The change

Two parts, in this order.

**2a — gate the branch on the project's source vocabulary.** Give `clarification_response` the
vocabulary it can already reach (`workflow.py` loads `self._vocabulary` at line 163, before both call
sites) and skip the ambiguity branch entirely when `"ISSUE"` is not among the project's source types:

```python
def clarification_response(
    request: RagRequest,
    known_entities: tuple[str, ...],
    source_types: tuple[str, ...] = (),
) -> RagResponse | None:
    ...
    # An overloaded noun is only overloaded where both senses exist. On a
    # documentation-only corpus "ticket" can only be the printed receipt, so
    # asking which one the user meant offers a choice the project cannot honour.
    available = {value.upper() for value in source_types}
    issue_sources_available = not available or "ISSUE" in available
    overloaded_record = (
        issue_sources_available
        and bool(re.search(r"\b(?:tickets?|boletos?)\b", normalized))
        and not explicit_identifier
    )
```

Update both call sites to pass `self._vocabulary.source_types`.

**2b — make the document context match conjugations.** Replace the whole-word alternation with
stem-anchored prefixes so `imprim*` / `reimprim*` / `impres*` all match:

```python
    document_context = bool(
        re.search(
            r"\b(?:print\w*|reprint\w*|receipts?|paper|"
            r"imprim\w*|reimprim\w*|impres\w*|recibos?|comprobantes?|papel)\b",
            normalized,
        )
    )
```

2a alone fixes the store persona. 2b is what stops the developer project mis-clarifying the same
Spanish questions, where the ambiguity is real but the printing sense is stated.

### Test — `tests/test_overloaded_record_clarification.py`

- All nine questions above, with `source_types=("PAGE",)`: none clarifies.
- The same nine with `source_types=("PAGE","CODE","ISSUE")`: only `"¿Dónde veo el estado del ticket?"`
  and the bare `"¿Puedo copiar un ticket?"`-style cases without a print stem clarify; every question
  carrying a conjugated print stem does not.
- `source_types=()` reproduces today's behaviour exactly for every case in
  `tests/test_clarification_identifiers.py`.

---

# STEP 3 — A continuation with nothing to continue is a standalone question

**The other half of "not responding cleanly", and a regression introduced by `30c0cba`.**

**File:** `app/workflow_support/fail_closed.py`

### Root cause

`30c0cba` added `LEADING_FRAGMENT_CONTINUATION`: a turn opening with a bare preposition is the tail of
the previous question. That is correct **when there is a previous question**.

`clarification_response` calls the same predicate on the **first** turn —
`needed, _reason = _conversation_resolution_decision(request.question)` — and returns
`AMBIGUOUS_FOLLOWUP` / *"¿A qué tema o entidad te refieres?"* whenever `needed` is `True` and there is
no history and no active subject. Opening a fresh chat with `"sobre el cierre de caja"` is exactly how
a store user starts.

### Reproduced — before and after `30c0cba`, same ten first turns

| question | `30c0cba~1` | `d21b29d` |
|---|---|---|
| `sobre las reimpresiones` | `False` EXPLICIT_SUBJECT | **`True` LEADING_FRAGMENT_CONTINUATION** |
| `sobre el cierre de caja` | `False` EXPLICIT_SUBJECT | **`True`** |
| `de los tipos de producto` | `False` EXPLICIT_SUBJECT | **`True`** |
| `para el flujo de precios` | `False` EXPLICIT_SUBJECT | **`True`** |
| `sobre el ticket` | `False` EXPLICIT_SUBJECT | **`True`** |
| `acerca del inventario` | `False` EXPLICIT_SUBJECT | **`True`** |
| `con el departamento de finanzas` | `False` EXPLICIT_SUBJECT | **`True`** |
| `about the reprints` | `False` EXPLICIT_SUBJECT | **`True`** |
| `from the product types` | `False` EXPLICIT_SUBJECT | **`True`** |
| `regarding the cash drawer` | `False` EXPLICIT_SUBJECT | **`True`** |

Ten of ten. Every one of these now answers a first-turn store question with *"which topic do you
mean?"*. The Step 1 fix in `34_FINAL_FIX_AND_LATENCY_PROMPT` is right about follow-ups and must stay;
only this caller is wrong.

### The change

The reason code exists precisely so the caller can tell the two apart. In `clarification_response`:

```python
    needed, reason = _conversation_resolution_decision(request.question)
    # A leading-fragment turn is a continuation of the turn before it. On a first
    # turn there is no turn before it, so it is not an ambiguous follow-up -- it
    # is a short standalone question, and retrieval can answer it. Asking "which
    # topic?" here is how a fresh chat opened with "sobre el cierre de caja"
    # stopped answering after 30c0cba.
    if reason == "LEADING_FRAGMENT_CONTINUATION":
        return None
```

placed immediately after the call, before the existing `if (not needed or ...)` guard. No other caller
of `_conversation_resolution_decision` changes: `conversation.py`'s own resolution path only reaches the
rule when there is history to carry.

### Test — extend `tests/test_prepositional_continuation.py`

- All ten first turns above, with empty `conversation_history` and empty `active_subject`, return
  `None` from `clarification_response`.
- The same question **with** a prior turn still resolves as a continuation in
  `_conversation_resolution_decision` — the `30c0cba` behaviour is untouched.
- `"what is MC"` with no history still returns `AMBIGUOUS_FOLLOWUP` — the branch is not dead.

---

# STEP 4 — Bind the client to a project explicitly, and show which one

**This is the "when I change account it answers from the wrong corpus" report.**

**Files:** `project-intelligence-backend/app/api/me.py`,
`project-intelligence-mobile/…/ProjectIntelligenceViewModel.kt`, `…/ProjectIntelligenceScreen.kt`

### Root cause

`ProjectIntelligenceViewModel.login()` line 86:

```kotlin
val projectId = session.user.assignedProjects.firstOrNull()?.projectId
```

`/v1/me` builds `assignedProjects` from `project_store.list_by_ids(...)`, and
`infrastructure/sql/project_repository.py:36` orders by `ProjectRecord.display_name`. The two display
names are `Tiendas 2.0 Store Assistant` and `Tiendas 3B Platform`, and `"2" < "3"`, so **the store
project always sorts first**. Any account assigned to both — which the developer account is, or this
report would not exist — is silently bound to `T2.0-STORE`, forever, with no picker and nothing in the
UI naming the active project (`ProjectIntelligenceScreen.kt` renders only `user.displayName`).

The developer then asks code and Jira questions of a corpus that is 23 Confluence pages of store
procedures, and gets refusals that look like a broken RAG. Switching accounts changes nothing about
this, which is why the symptom reads as "changing account breaks it".

Account switching itself is already fixed — `ExampleIdentityGateway` forces `Prompt.SELECT_ACCOUNT`,
and `logout()` resets the whole `ProjectIntelligenceUiState`.

### The change

**4a — backend, deterministic order.** In `me.py`, return assignments in the order the Graph attribute
lists them, falling back to `project_id` for anything the attribute does not order, instead of
inheriting the SQL `display_name` sort. Display name is a label; it must not decide authorization
scope.

**4b — client, show the binding.** Render the active project's `displayName` in the chat header, beside
the user avatar. One line of UI that would have made this report a five-second diagnosis.

**4c — client, pick when there is a choice.** When `assignedProjects.size > 1`, do not auto-select:
show a picker, and keep the selection keyed by `session.user.userId` so switching accounts cannot
inherit the previous account's project. With exactly one assignment, keep today's auto-select.

Minimum that removes the symptom: 4b. Ship 4a and 4c with it — 4a is three lines and 4c is what makes
the developer account usable at all.

### Test

- Backend: `/v1/me` with Graph `Projects = ["T2.0", "T2.0-STORE"]` returns `T2.0` first regardless of
  display name; with the attribute order reversed, so is the response.
- Client: a `SessionResponse` with two assignments leaves `authorizedProjectId` null and sets a
  pending-selection state; with one assignment it auto-selects as today. Selecting a project, signing
  out, and signing in as a different user leaves no carried selection.

---

# STEP 5 — Build the store gold suite; you currently cannot measure this persona at all

Every artefact in `.run/` — `step4-before*`, `step7-after*` — is `T2.0`. `exposed_project_ids` is
`["T2.0", …]` on every row. **There has never been an evaluation run against `T2.0-STORE`**, which is
why three deterministic, 100%-reproducible defects shipped unnoticed.

The gold data already exists and is bilingual by construction:
`docs/store-assistant/{en,es}/topics/10_{CANONICAL_QUESTION_INDEX,INDICE_DE_PREGUNTAS_CANONICAS}.md`
carry **184 canonical questions per language across 28 sections**, each with its target page and
bracketed section identifier — the citation anchors are the gold labels.

- Extend `evaluation/build_gold_suites.py` with a parser for the canonical index; emit
  `evaluation/store_gold_suites.jsonl` (368 cases, `query_language` `en`/`es`, gold = the section
  identifiers the index routes to).
- Run Layer 1 and the generation lane for `T2.0-STORE` **before** Steps 1–3 and after. The before-run is
  the evidence that the refusals were routing, not retrieval.
- Add `refusal_precision` and `no_answer_false_positive_rate` per language to the acceptance gate. On
  `T2.0` today they are `0.53` and `0.10` — half of all refusals are wrong. Do not let `T2.0-STORE`
  ship without a number here.

---

# STEP 6 — Rebuild, then verify both personas

`api` and `rag` are containers; editing files changes nothing until they are rebuilt.

```bash
cd ~/Desktop/project-intelligence-backend && ./scripts/prepare_and_start_local_app.sh
```

### Store user — `store_user@naveenrajelangovan1997gmail.onmicrosoft.com`, project `T2.0-STORE`

| # | question | must |
|---|---|---|
| 1 | `¿Cómo hago entrega de valores?` | answer; trace shows `query_intent` **not** `DELIVERY`, `source_types=('PAGE',)` |
| 2 | `¿Cómo filtro prioridad?` | answer, same trace assertion |
| 3 | `No salió el ticket de tiempo aire.` | answer — **not** `AMBIGUOUS_SOURCE_FAMILY` |
| 4 | `¿Cómo reimprimo un ticket?` | answer, citing the printing topic page |
| 5 | `sobre el cierre de caja` as the **first** turn of a fresh chat | answer — **not** `AMBIGUOUS_FOLLOWUP` |
| 6 | then `y si la impresora falla?` | answer, carrying the subject from turn 5 |
| 7 | `show me the open jira issues` | refuse cleanly — the store project has no issues and must say so |

### Developer — `developer@naveenrajelangovan1997gmail.onmicrosoft.com`, project `T2.0`

| # | question | must |
|---|---|---|
| 8 | header on sign-in | names the active project; with two assignments, a picker appears |
| 9 | select `T2.0`, ask `which classes implement the price check flow` | answer from code, `query_intent=IMPLEMENTATION` |
| 10 | `what is the status of the delivery for T0` | `DELIVERY`, `source_types=('ISSUE',)` — Step 1 must not have disabled Jira where it exists |
| 11 | `¿Cómo hago entrega de valores?` | still `DELIVERY` here — `T2.0` has an issue tracker, so the routing is right |
| 12 | switch to `store_user`, then back | the project shown matches the account; no carried selection |

### Acceptance gate — all of it, or it does not ship

- Full RAG suite green. 73 test files today; the three new files add to that. No test weakened,
  skipped, or shimmed.
- `wc -l app/workflow.py` ≤ 450.
- Every Step 1–3 unit test passes with `source_types=()` producing **byte-identical** decisions to
  `d21b29d` — the unobserved-vocabulary path is untouched.
- Layer 1 on `T2.0`: no regression in `recall_at_k`, `ndcg_at_k`, gold resolution (1.0) or leakage (0),
  in either language, and no widening of the language gap.
- Layer 1 + generation on `T2.0-STORE`, before and after: refusal rate falls, `refusal_precision` does
  not, `cross_project_leakage` is 0 in both runs.
- Rows 1–7 above answer; rows 9–11 behave as they do today.

---

## 7. Found but not fixed here

- **`authorized_project_policies` keeps any `user:` policy** (`retrieval_pipeline.py:287`) regardless of
  which user it names, because a user scope is cross-project by design. Not exploitable today —
  ingestion writes only `access_policy_id = project:<id>`, and the backend mints the scopes server-side
  from the verified `oid` (`chat_policy.py:12`) — but the RAG boundary should carry the caller's
  principal and match `user:{oid}` exactly rather than the bare prefix. Hardening, own change, own test.
- **`catalog_answers.py` is hard-gated to `project_id == "T3B-COMPANY"`.** It cannot fire for `T2.0` or
  `T2.0-STORE`. Either wire the real catalog project or say in the module docstring that it is the
  synthetic-corpus path, so the next reader does not assume the store persona has a catalog answer.
- **Spanish is measurably worse on `T2.0`** — `hit_rate@16` 0.40 es vs 0.71 en, `ndcg@16` 0.175 vs
  0.407, on equal `recall@25`. That is a **ranking** gap, not a retrieval gap: the reranker finds the
  right documents and puts them below 16. Steps 1–3 will improve the Spanish store numbers because the
  trigger words are Spanish, but they do not touch this. It needs its own investigation against the new
  store suite.
- **`docs/store-assistant/README.md` still says `DRAFT — NOT APPROVED FOR INGESTION`** while
  `config/local-project.T2.0-STORE.json` ingests 23 published pages. Reconcile the status line; a future
  reader will otherwise trust the wrong one.
- **The store corpus README names space `Store_Users_Douments`** (typo, and it does not match the
  `spaceKey: "StoreUsers"` actually configured). Cosmetic, but it is the only place the space is named
  in prose.

## 8. What this document does not claim

Steps 1, 2 and 3 were reproduced by executing the shipped `d21b29d` functions directly against the
project vocabularies and question sets shown, with the pre-`30c0cba` module as the control for Step 3.
Step 4's mechanism was read from source and confirmed by the display-name sort; it was **not** observed
against a live Entra assignment, because the local stack was not running during this audit — row 12 of
Step 6 is what proves it. No latency claim is made here, and no threshold that judges truth is moved by
any step.
