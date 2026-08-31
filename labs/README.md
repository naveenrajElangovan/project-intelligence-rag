# Retrieval and security learning labs

All labs are offline by default and exercise production classes or the same LangGraph primitives. Run from this repository.

## 3. Deterministic LangGraph

```bash
.venv/bin/python labs/lab03_langgraph.py
```

Expected: both English and Spanish branches run, candidates deduplicate, and the graph chooses the grounded route.

Exercises: return no candidates; make one branch fail; add a bounded retry node.

## 4. Chroma authorization, multilingual retrieval, and local reranking

```bash
.venv/bin/python labs/lab04_chroma_security.py
```

Expected: the exact namespace, `project_id`, and `access_policy_id` sent by the production retriever, plus a one-chunk-per-source reranked result.

Exercises: attempt a second project policy; change `top_k`; return two chunks from one source.

## 5. RAG security and citations

```bash
.venv/bin/python labs/lab05_rag_security.py
```

Expected: document instructions remain delimited untrusted data, control characters are removed, and an invalid citation is rejected.

Exercises: add injection text in Spanish; cite a missing source; remove all evidence and inspect the safe route.

Automated coverage: `tests/test_learning_labs.py`, `tests/test_bilingual_workflow.py`, and `tests/test_retrieval.py`.
