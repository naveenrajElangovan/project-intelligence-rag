# Beginner Project: Project Research Router

Build a small offline LangGraph application that routes a project question to the correct
knowledge source, searches fake evidence, retries once when necessary, and either returns a
grounded answer or safely reports that evidence is unavailable.

This project teaches the same fundamentals used by the production RAG service without calling an
LLM, Chroma, GitHub, Jira, or Confluence.

## The graph you will build

```text
START
  -> classify_source
  -> plan_query
  -> search
  -> evaluate_evidence
       -> answer                         when evidence exists
       -> retry -> search                when evidence is missing and retry is unused
       -> unavailable                    when evidence is still missing
  -> END
```

## Files

- `starter.py`: your implementation. Complete each `TODO` in numerical order.
- `check_project.py`: offline acceptance checker. Do not change it while solving the project.

## Step 1: understand the state

`ResearchState` is the graph's shared notebook. Nodes receive the current state and return only
the fields they add or change. LangGraph merges those updates into the state.

The state must eventually contain:

- the original question;
- the selected source;
- planned search queries;
- retrieved evidence;
- the current search attempt;
- the final route and answer.

## Step 2: implement the nodes

Complete the TODOs in this order:

1. `classify_source`: select GitHub, Jira, Confluence, or unknown using the provided keywords.
2. `plan_query`: store the original question as the first query and set attempt `1`.
3. `search`: search only the selected source and remove duplicate evidence.
4. `evaluate_evidence`: return `answer`, `retry`, or `unavailable`.
5. `retry`: add one broader source-specific query and set attempt `2`.
6. `answer`: produce a small answer based only on retrieved evidence.
7. `unavailable`: return a safe no-evidence answer.
8. `build_graph`: register nodes, edges, and conditional routes, then compile the graph.

## Safety rules

- Search only the source selected by `classify_source`.
- Never treat the user's question as evidence.
- Never invent an answer when `candidates` is empty.
- Permit exactly one retry.
- Every route must reach `END`.

## Run the checker

From the RAG repository:

```bash
.venv/bin/python labs/langgraph_research_router/check_project.py
```

The checker covers:

- GitHub routing and answering;
- Jira routing and answering;
- Confluence routing and answering;
- a vocabulary mismatch recovered by one retry;
- an out-of-domain question that safely ends as unavailable;
- termination after no more than two search attempts.

## Definition of done

The project is complete when the checker reports all scenarios passed and you can explain:

1. what information lives in state;
2. what each node changes;
3. where the graph makes decisions;
4. why the retry cannot loop forever;
5. why an answer cannot be generated without evidence.

## Optional challenges

After the required checker passes:

1. Add Spanish routing keywords.
2. Search GitHub and Confluence for a cross-source architecture question.
3. Add a `search_history` field recording source, query, and result count.
4. Simulate a search exception and route to a typed error result.
5. Add a maximum total-step budget independent of the retry counter.
