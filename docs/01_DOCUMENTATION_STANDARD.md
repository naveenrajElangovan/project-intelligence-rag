# Implementation prompt — make every function in the platform readable by someone with no Python knowledge

Repos: `~/Desktop/project-intelligence-rag`, `~/Desktop/project-intelligence-ingestion`,
`~/Desktop/project-intelligence-backend`.

**This is a standalone task. It changes no logic.** Every commit adds or rewrites documentation. If a
commit changes a line of executable code, it belongs in a different pull request.

The goal in one sentence: **a new joiner, a product owner, or an auditor should be able to open any file
and understand what the code does, where it sits in the system, and how it behaves — without knowing
Python.**

---

## 1. Verified state — measured 2026-09-07

Docstring coverage across the three services:

| | modules | classes | functions | public functions |
|---|---|---|---|---|
| RAG | 23/49 (47%) | 32/76 (42%) | 250/532 (47%) | 97/191 (51%) |
| backend | 22/58 (38%) | 14/78 (18%) | **38/224 (17%)** | 25/144 (17%) |
| ingestion | 8/29 (28%) | 9/47 (19%) | **35/254 (14%)** | 14/110 (13%) |
| **total** | 53/136 (39%) | 55/201 (27%) | **323/1,010 (32%)** | 136/445 (31%) |

Two thirds of the platform's functions say nothing about themselves. The longest functions are the worst
documented:

| lines | documented | function |
|---|---|---|
| **682** | **no** | `rag: workflow_nodes/answering.py::_generate` |
| 610 | yes | `rag: workflow_nodes/planning.py::_plan_queries_core` |
| 503 | yes | `rag: workflow_nodes/retrieval.py::_rerank` |
| 399 | **no** | `rag: workflow_nodes/retrieval.py::_retrieve` |
| 390 | **no** | `rag: workflow_nodes/answering.py::_verify_grounding` |
| 161 | **no** | `ingestion: service.py::_ingest_github_scopes` |
| 158 | **no** | `ingestion: api/github.py::github_webhook` |
| 143 | **no** | `ingestion: structured_chunking.py::chunk` |

A 682-line undocumented function is the single least approachable thing in the platform. It is also the
one that decides what every user reads.

---

## 2. The standard

### 2.1 Every function, without exception

Public, private, one-liner, nested — **every** `def` and `async def` carries a docstring. A function too
small to describe is a function whose name should describe it, and the docstring then says so in one
line. There is no size threshold below which "it is obvious" is accepted, because "obvious" assumes the
reader knows Python, and the reader does not.

### 2.2 The five sections

Functions **15 lines or longer** use all five. Shorter functions use the summary line and add any
section that is not self-evident.

```python
def resolve_access_policy(rules, document, shared_policy):
    """Decide which group of people is allowed to see one document.

    WHAT IT DOES
        Looks at a document that has just been collected from Confluence, Jira or
        GitHub, and stamps it with a label saying who may read it. The label is
        either "everyone on this project" or "only this department".

    WHERE IT RUNS
        In the ingestion service, on the machine that collects documents. It runs
        once per document, after the document has been downloaded and checked for
        secrets, and immediately before the document is written into the search
        database. Nothing a user types ever reaches this function.

    HOW IT WORKS
        1. Reads the list of rules that the project owner wrote in the project
           configuration file. A rule says, for example: "any Confluence page whose
           title starts with [FINANCE] belongs to the Finance department."
        2. Walks the rules in order and stops at the first one that matches this
           document.
        3. If a rule matched, returns that rule's label.
        4. If no rule matched, returns the project-wide label, which means everyone
           with access to the project can read the document.

    INPUTS
        rules           The list of labelling rules for this project, read from
                        configuration. May be empty.
        document        The document that was just collected, including its title,
                        its source system, and where it came from.
        shared_policy   The label to use when no rule matches - the project-wide one.

    GIVES BACK
        One label, as text, for example "department:T3B-COMPANY:FINANCE_AND_ACCOUNTING".
        Always a label; never empty.

    IF SOMETHING GOES WRONG
        This function cannot fail. Rules were already checked for validity when the
        service started, so a broken rule stops the service at startup rather than
        producing a wrong label here.

    WHY IT MATTERS
        This label is the only thing standing between a Finance document and a store
        employee's search results. Getting it wrong is a data leak, not a bug.
    """
```

Section names are fixed. Use these exact words — `WHAT IT DOES`, `WHERE IT RUNS`, `HOW IT WORKS`,
`INPUTS`, `GIVES BACK`, `IF SOMETHING GOES WRONG`, `WHY IT MATTERS` — so a reader learns the shape once
and a tool can check for them. `WHY IT MATTERS` is required only where the rule is not obvious from the
name; the other six are always required on functions of 15 lines or more.

### 2.3 Write for a reader who does not know Python

| do not write | write instead |
|---|---|
| "Returns a `tuple[str, ...]`" | "Gives back a list of labels, as text" |
| "Raises `PermissionError`" | "Stops the request and reports 'not allowed'" |
| "Iterates the candidate set" | "Goes through the documents that were found, one at a time" |
| "Async generator yielding NDJSON events" | "Sends the answer to the user's screen a piece at a time, as it becomes ready" |
| "Mutates state in place" | "Updates the shared record that the later steps read" |
| "O(n log n) over the corpus" | "Gets slower as the number of documents grows, but only slightly" |
| "Idempotent" | "Running it twice does the same thing as running it once" |
| "Fail-closed" | "If anything is unclear, it refuses rather than guessing" |

Rules:

- **Define a term the first time a module uses it**, then use it consistently. `chunk`, `embedding`,
  `rerank`, `grounding`, `access policy`, `namespace` — all of these need one sentence of explanation
  somewhere the reader can reach.
- **No abbreviations without expansion** on first use in a module: RAG, BM25, RRF, MPS, E5, TTL, JWKS.
- **Say what happens, not what the code is.** "Checks whether the user is allowed" beats "calls
  `_authorized_policy_filter`".
- **No filler.** Delete "simply", "just", "basically", "obviously". If it were obvious the docstring
  would not be needed.
- **Present tense, active voice, short sentences.** "Reads the rules. Picks the first match." not "The
  rules will have been read, whereupon a match is selected."

### 2.4 Module headers: where this file sits in the whole system

Every file opens with a header that lets a reader place it without opening anything else.

```python
"""Turn a collected document into small, searchable pieces.

PART OF
    The ingestion service - the part of the platform that reads Confluence pages,
    Jira issues and GitHub files and puts them into the search database.

WHEN THIS RUNS
    After a document has been downloaded and checked for secrets, and before it is
    written to the search database. Roughly the middle of the collection pipeline:

        download -> security check -> [ THIS FILE ] -> write to database

WHY IT EXISTS
    A search engine cannot look inside a fifty-page document and point at the one
    paragraph that answers a question. So every document is cut into pieces of a few
    hundred words each, and each piece is stored and searched separately. Cutting in
    the wrong place - in the middle of a table, or halfway through a procedure - is
    the most common cause of a bad answer, which is why this file is careful about
    where it cuts.

MAIN ENTRY POINT
    chunk() - hand it a document, get back its pieces.

READ NEXT
    embedding.py, which turns each piece into the numbers the search database
    actually stores.
"""
```

### 2.5 Package README and glossary

- **One `README.md` per package** (`domain/`, `application/`, `infrastructure/`, `interface/`, or the
  current equivalents): what lives here, what does not, and the three files to read first.
- **One `docs/GLOSSARY.md` per service**, plain-language, one paragraph per term, no code. Every domain
  word used in any docstring appears here. This is what makes "define on first use" affordable — the
  docstring gives one sentence and the glossary gives the paragraph.
- **One `docs/HOW_A_QUESTION_IS_ANSWERED.md`** in the RAG repo: the end-to-end journey of a single
  question, in plain language, naming the files it passes through in order. One page, no code. This is
  the document a non-engineer reads first, and the one that makes every other docstring make sense.

---

## 3. Enforcement — so this does not decay in a month

Documentation that is not checked is documentation that rots. Three gates, all cheap.

### 3.1 Ruff, for the mechanical rules

```toml
[tool.ruff.lint]
extend-select = ["D"]                 # pydocstyle

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["D"]
```

This enforces: a docstring exists, it starts with a capital, it ends with a period, the summary is one
line, and the blank-line layout is consistent. It does **not** judge content.

### 3.2 A coverage ratchet

Add `interrogate` and fail the build if coverage drops:

```toml
[tool.interrogate]
ignore-init-module = true
fail-under = 32          # today's real number; raise it, never lower it
exclude = ["tests"]
```

Raise `fail-under` in every documentation PR — 32 → 45 → 60 → 80 → 100. A ratchet gets you to 100%
without a documentation sprint that blocks feature work for a month.

### 3.3 A structure test, for the five sections

`tests/test_documentation.py`, one per repo:

```python
REQUIRED = ("WHAT IT DOES", "WHERE IT RUNS", "HOW IT WORKS",
            "INPUTS", "GIVES BACK", "IF SOMETHING GOES WRONG")
BANNED = ("simply", "just ", "basically", "obviously", "TODO", "FIXME", "XXX")

def test_every_module_has_a_header() -> None: ...
def test_long_functions_carry_every_section() -> None:
    """Any function of 15+ lines documents all six required sections."""
def test_docstrings_avoid_filler_words() -> None: ...
def test_every_glossary_term_is_defined() -> None:
    """Every term used in a docstring from the glossary list exists in GLOSSARY.md."""
```

Walk the source with `ast`, measure `end_lineno - lineno`, and assert. Allow an explicit, reviewed
exemption list that starts empty and must stay short.

### 3.4 The human check that cannot be automated

Once a month, pick **ten docstrings at random** and have someone who does not write Python read them
aloud and say what the function does. Anything they cannot explain gets rewritten. No tool can tell you
whether prose is understandable; a person reading it can, in fifteen minutes.

### 3.5 Publish it, so it is actually read

Add `mkdocs` with `mkdocstrings`:

```
mkdocs.yml
docs/
  index.md                      -> the platform in one page
  how-a-question-is-answered.md
  glossary.md
  reference/                    -> generated from the docstrings
```

`mkdocs serve` turns the docstrings into a browsable handbook. Documentation nobody can find is
documentation nobody reads, and a non-engineer will not clone a repository to read a docstring.

---

## 4. Order of work

Do not start at `a` and end at `z`. Document in the order a reader needs.

**Step 1 — the map (half a day, highest value).**
Write `docs/HOW_A_QUESTION_IS_ANSWERED.md`, `docs/GLOSSARY.md` and the package READMEs first. Everything
after this is easier because terms are already defined.

**Step 2 — the module headers.** All 136 modules, three services. Fast, mechanical, and it makes the
codebase navigable immediately.

**Step 3 — the eight monsters.** The undocumented functions over 100 lines listed in §1, starting with
`_generate` (682 lines). These are where a reader gets lost. Documenting a function this long will
expose that it does six things; **write down the six things, do not split the function** — splitting is
a separate change and this task changes no code.

**Step 4 — security- and money-critical paths, whatever their size.** Anything that decides who may see
what, anything that writes to a customer-visible store, anything that refuses a user. Access policy
filtering, the authorization scopes, the ingestion write and delete paths, the refusal decisions. These
get the `WHY IT MATTERS` section without exception.

**Step 5 — public functions**, then **private functions**, ratcheting `fail-under` as you go.

**Step 6 — turn on the gates.** Ruff `D`, the structure test, `fail-under = 100`, and the mkdocs build
in CI.

Run steps 2–5 as **one pull request per package**, so review stays readable and a reviewer can check the
prose rather than skim a thousand-line diff.

---

## 5. Two worked examples from the current code

### 5.1 Short and security-critical — `app/retrieval.py::_authorized_policy_filter`

Today:

```python
def _authorized_policy_filter(
    access_policy_ids: tuple[str, ...],
) -> dict[str, dict[str, str | list[str]]]:
    policies = tuple(dict.fromkeys(value for value in access_policy_ids if value))
    if not policies:
        raise PermissionError("At least one authorized access policy is required.")
    ...
```

After:

```python
def _authorized_policy_filter(access_policy_ids):
    """Build the "who is allowed to see this" condition sent to the search database.

    WHAT IT DOES
        Turns the list of groups the current user belongs to into a filter that the
        search database applies to every document before it is even considered.

    WHERE IT RUNS
        In the answering service, on every single search. It runs before any document
        is read, so a document the user may not see is never loaded into memory, never
        scored, and never shown to the language model.

    HOW IT WORKS
        1. Removes empty entries and duplicates from the list of groups.
        2. If nothing is left, stops the request - see below.
        3. Builds a condition meaning "the document's owner label must be one of
           these groups" and hands it to the search database.

    INPUTS
        access_policy_ids   The groups this user may read from, worked out by the
                            backend from the company directory. The user's own app
                            can never set or change this list.

    GIVES BACK
        A condition the search database understands. Never an empty condition.

    IF SOMETHING GOES WRONG
        An empty list stops the request with "not allowed". This is deliberate: an
        empty filter would mean "no restriction", which would show every document in
        the project to someone with no permissions at all.

    WHY IT MATTERS
        This is the boundary between one department's documents and another's. It
        fails closed on purpose - an unclear permission refuses rather than guesses.
    """
```

### 5.2 Long and undocumented — `workflow_nodes/answering.py::_generate` (682 lines)

Do not split it in this task. Document it as it is, and write the header so the six things it does are
visible without reading it:

```python
async def _generate(self, state):
    """Write the answer, one verified sentence at a time.

    WHAT IT DOES
        Takes the documents that survived searching and ranking, asks the language
        model to write an answer using only those documents, and checks the answer as
        it is being written.

    WHERE IT RUNS
        In the answering service, near the end of the journey. Everything before it
        was about finding evidence; everything after it is about proving the answer
        matches that evidence:

            search -> rank -> check evidence -> [ THIS STEP ] -> check the wording
                                                              -> check the sources

    HOW IT WORKS
        1. Chooses how detailed the answer should be, from the kind of question asked.
        2. Assembles the evidence into the text handed to the language model, cutting
           it down if there is more than the model can read at once.
        3. Asks the model to write the answer, receiving it a few words at a time.
        4. Checks each finished sentence against the evidence as it arrives.
        5. If the model stops responding, keeps the sentences already checked rather
           than losing the whole answer.
        6. Records how long each part took, and what was dropped and why.

    INPUTS
        state   The shared record for this question, carrying the question itself, the
                documents found, and the language to answer in.

    GIVES BACK
        The same shared record with the written answer added, plus notes on anything
        that was removed and why.

    IF SOMETHING GOES WRONG
        If the model is too slow, the answer is cut to the sentences already checked
        and marked as shortened. If nothing was checked, the request fails and the
        user gets a refusal rather than an unverified answer.

    WHY IT MATTERS
        This is the only place in the platform where new sentences are created. Every
        other step finds, filters or checks. That is why it is fenced on both sides.

    NOTE FOR MAINTAINERS
        This function does six separable things, listed above as steps 1 to 6. It is
        the largest function in the platform. Splitting it is worthwhile but is a
        code change and does not belong in a documentation commit.
    """
```

---

## 6. Acceptance

- `interrogate` reports **100%** across all three services; `fail-under = 100` in CI.
- Ruff `D` rules pass with no per-file ignores outside `tests/`.
- The structure test passes: every module has a header, every function of 15+ lines carries all six
  sections, no filler words, no `TODO` left in a docstring.
- `GLOSSARY.md`, `HOW_A_QUESTION_IS_ANSWERED.md` and one README per package exist; every domain term
  used anywhere appears in the glossary.
- `mkdocs build --strict` succeeds in CI and the site is published somewhere a non-engineer can open.
- **The human check passes:** someone who does not write Python reads ten randomly chosen docstrings and
  correctly explains what each function does. This is the real acceptance test; the rest are proxies
  for it.
- `git diff --stat` for the whole effort shows changes to docstrings, README and docs files **only**.
  Any executable line changed means the work leaked into a different task.

## 7. What this document does not claim

The coverage numbers, the function line counts and the list of undocumented long functions were computed
from the working tree on 2026-09-07 by walking every module's syntax tree. The two worked examples are
faithful to the current signatures and behaviour of those functions, but they are proposals for wording,
not transcriptions of an agreed standard — expect the first package's review to sharpen the phrasing,
and once it does, treat that package as the reference for the rest.
