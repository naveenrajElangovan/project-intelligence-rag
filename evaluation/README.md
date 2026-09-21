# Evaluation entrypoint

This is the authoritative index for the RAG evaluation package. Run commands from
the repository root with `.venv/bin/python -m evaluation.<module>`. Live tools use
the configured primary Chroma collection unless their help explicitly documents an
override. Never change truth thresholds merely to make a run pass.

## Release and correctness gates

| Module | Why it exists | When to run it |
|---|---|---|
| `run_retrieval_eval.py` | Measures gold resolution, candidate recall, reranked section recall, ranking quality, and leakage; can also invoke generation. | Every retrieval, chunking, corpus, embedding, reranking, or routing change. |
| `run_ragas_eval.py` | Runs the pinned external generation judges over reviewed references. | When generation prompts/models or grounding behavior change. |
| `run_phase4_retrieval_gate.py` | Proves the EventType registry and indexed sections are retrievable from the active live corpus. | After EventType ingestion or collection-route changes. |
| `run_second_project_gate.py` | Builds an isolated second-project fixture and checks route behavior and zero leakage. | After authorization, collection, or provider-routing changes. |
| `run_live_acceptance.py` | Exercises the deployed HTTP answer contract with answerable and absent-knowledge cases. | Before release and after workflow, model, or service configuration changes. |
| `run_reproducibility_probe.py` | Fingerprints the complete public response across repeated live requests. | After ordering, concurrency, sampling, cache, or model changes; use three 10-run batches for a release claim. |
| `scan_event_type_coverage.py` | Compares the authoritative Kotlin enum with an exact live Chroma manifest. | After ingesting or reindexing `store-core-kotlin`. |

The coverage scan must read the checked-out Kotlin source, never a manifest-derived
snapshot. From this repository, the sibling source checkout is addressed explicitly:

```bash
.venv/bin/python -m evaluation.scan_event_type_coverage \
  --source ../T3B/store-core-kotlin/shared/src/commonMain/kotlin/com/tiendas3b/shared/core/domain/model/event/EventType.kt \
  --project-id T2.0 \
  --collection jira-stage-20260911-jira-complete-v3
```

## Dataset builders and references

| Module/file | Why it exists | When to use it |
|---|---|---|
| `build_gold_suites.py` | Derives maintained gold cases from canonical source material. | When reviewed source documentation changes. |
| `build_bilingual_reference_template.py` | Creates the EN/ES reviewed-reference skeleton required by judge lanes. | When adding bilingual generation cases. |
| `build_jira_suite.py` | Builds Jira cases from an authorized, stable issue snapshot. | After Jira schema/mapping changes. |
| `build_t2_dataset.py` | Produces the T2 project evaluation dataset. | When the reviewed T2 source set changes. |
| `bilingual_gold_suites.jsonl` | Reviewed bilingual generation cases. | Input to bilingual evaluation. |
| `gold_suites.jsonl` | Developer gold registry. | Default developer retrieval/generation input. |
| `store_gold_suites.jsonl` | Store-operations gold registry. | Store retrieval/generation input. |
| `jira_conversation_suite.json` | Multi-turn Jira cases. | Conversation/provider regression runs. |
| `generalization_developer_cases.json` | Novel developer live cases. | Developer HTTP acceptance. |
| `generalization_store_cases.json` | Novel store live cases. | Store HTTP acceptance. |
| `paraphrase_groups.json` | Reviewed equivalence groups. | Paraphrase invariance scoring. |
| `ragas_dataset.example.jsonl` | Schema example, not a measured dataset. | Authoring a new judge dataset. |
| `suites.json` | Declared suite registry and gates. | Read by release evaluation; edit only through an explicit gate decision. |

## Calibration and comparison

| Module | Why it exists | When to run it |
|---|---|---|
| `calibrate_threshold.py` | Evaluates score distributions without silently changing a gate. | When a reviewed labelled dataset justifies threshold analysis. |
| `calibrate_phase2_thresholds.py` | Replays Phase 2 candidates across threshold choices. | During an explicit Phase 2 calibration exercise. |
| `compare_nonjira_application.py` | Compares non-Jira application behavior across runs. | After provider changes that might regress repository/document questions. |
| `run_nonjira_application_baseline.py` | Captures the comparable non-Jira baseline. | Before the corresponding provider/routing change. |
| `pairwise_judge.py` | Implements deterministic pair preparation and pairwise judge logic. | Library used by the pairwise runner. |
| `run_pairwise_judge.py` | Compares baseline and candidate generation artifacts. | When deciding whether a generation change is better without relying on aggregate scores alone. |
| `score.py` | Computes common deterministic metrics. | Library/CLI support for evaluation pipelines. |
| `score_jira_review.py` | Scores manually reviewed Jira outputs. | After completing a Jira review sheet. |
| `deterministic_evaluators.py` | Contains content-local deterministic evaluator functions. | Imported by evaluation and publishing tools. |

## Live diagnostics and benchmarks

| Module | Why it exists | When to run it |
|---|---|---|
| `inspect_live_retrieval.py` | Shows live candidates for one query. | Diagnosing a retrieval miss. |
| `inspect_grounding_evidence.py` | Shows the evidence shape reaching grounding. | Diagnosing an unsupported or over-refused answer. |
| `inspect_page_reachability.py` | Checks whether a page/section can be reached. | Diagnosing Confluence section misses. |
| `inspect_confluence_sources.py` | Inventories authorized Confluence records. | Diagnosing source ingestion or routing. |
| `inspect_live_project_overview.py` | Exercises project-overview retrieval. | Diagnosing overview completeness. |
| `benchmark_lexical_startup.py` | Measures lexical cache construction/startup. | After lexical indexing/cache changes. |
| `benchmark_ollama_decode.py` | Separates Ollama prefill and decode behavior. | Diagnosing generation latency. |
| `benchmark_stream.py` | Measures streaming timing and contract behavior. | After streaming or timeout changes. |
| `run_authenticated_jira.py` | Runs authenticated Jira scenarios through the supported boundary. | Manual integration verification with valid local credentials. |
| `audit_jira_results.py` | Audits saved Jira result completeness and shape. | After a live Jira evaluation. |
| `audit_jira_status.py` | Checks the status/freshness of Jira evaluation inputs. | Before trusting a Jira run. |

## Phoenix and publishing support

| Module | Why it exists | When to use it |
|---|---|---|
| `publish_quality_run.py` | Publishes immutable run metadata and aggregates. | After a completed comparable quality run. |
| `phoenix_client.py` | Provides the constrained Phoenix API adapter. | Imported by publishing/evaluation tools. |
| `phoenix_assets.py` | Defines dataset/experiment asset shapes. | Imported when creating Phoenix assets. |
| `sync_prompts.py` | Synchronizes Git-versioned prompt metadata without making Phoenix a runtime source. | During a controlled prompt release. |

## Minimal release sequence

1. Run the relevant corpus-specific retrieval suite.
2. Run Phase 4 after EventType or ingestion changes.
3. Run generation and RAGAS when answer construction changed.
4. Run both live generalization matrices.
5. Run three independent 10-run reproducibility batches.
6. Run the second-project isolation gate after any authorization/routing change.
7. Run the full test suite, then publish only immutable comparable results.
