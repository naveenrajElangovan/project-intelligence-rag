import asyncio
from types import SimpleNamespace

from langchain_core.documents import Document

from app.models import RagRequest, StructuredConversationScope
from app.providers.contracts import ExecutionMode, ProviderName, StructuredOperation
from app.providers.indexed import IndexedProviderAdapter
from app.providers.router import select_providers
from app.workflow_nodes.providers import ProviderNodesMixin


ENABLED = (ProviderName.JIRA, ProviderName.GITHUB, ProviderName.CONFLUENCE)


def test_jira_count_routes_to_complete_structured_operation() -> None:
    selection = select_providers("How many tickets do we have in Jira for POS?", ENABLED)

    assert selection.mode == ExecutionMode.STRUCTURED
    assert selection.providers == (ProviderName.JIRA,)
    assert selection.structured_query is not None
    assert selection.structured_query.operation == StructuredOperation.COUNT
    assert selection.structured_query.filters == {"labels": ("POS",)}


def test_spanish_distribution_is_typed_and_scoped() -> None:
    selection = select_providers(
        "¿Cuál es el desglose por estado de todos los tickets Jira para BOT?", ENABLED
    )

    assert selection.mode == ExecutionMode.STRUCTURED
    assert selection.structured_query is not None
    assert selection.structured_query.operation == StructuredOperation.DISTRIBUTION
    assert selection.structured_query.group_by == "status"
    assert selection.structured_query.filters == {"labels": ("BOT",)}


def test_cross_provider_question_selects_controlled_federation() -> None:
    selection = select_providers(
        "Is Jira ticket T0-120 implemented in GitHub and documented in Confluence?",
        ENABLED,
    )

    assert selection.mode == ExecutionMode.FEDERATED
    assert selection.providers == ENABLED


def test_non_jira_question_is_legacy_passthrough() -> None:
    selection = select_providers("How does authentication work?", ENABLED)

    assert selection.mode == ExecutionMode.LEGACY
    assert selection.reason == "LEGACY_PASSTHROUGH"


def test_disabled_provider_fails_closed_without_querying_another_provider() -> None:
    selection = select_providers(
        "What is the status of Jira ticket T0-120?", (ProviderName.GITHUB,)
    )

    assert selection.mode == ExecutionMode.UNAVAILABLE
    assert selection.providers == (ProviderName.JIRA,)


class _SnapshotRetriever:
    async def authorized_source_snapshot(self, source_types):
        assert source_types == ("ISSUE",)
        return (
            (
                _issue("jira:c:T0-1:CURRENT", "T0-1", "POS sale", "POS", "Done"),
                _issue("jira:c:T0-1:CURRENT", "T0-1", "POS sale duplicate", "POS", "Done"),
                _issue("jira:c:T0-2:CURRENT", "T0-2", "BOT order", "BOT", "To Do"),
                _issue("jira:c:T0-3:CURRENT", "T0-3", "BOT payment", "BOT", "In Progress"),
                Document(
                    page_content="historical",
                    metadata={
                        "provider": "JIRA",
                        "jira_chunk_kind": "CHANGELOG",
                        "issue_key": "T0-1",
                    },
                ),
            ),
            True,
        )


def _issue(source_id: str, key: str, title: str, label: str, status: str) -> Document:
    return Document(
        page_content=title,
        metadata={
            "provider": "JIRA",
            "source_type": "ISSUE",
            "source_id": source_id,
            "jira_chunk_kind": "CURRENT",
            "issue_key": key,
            "title": title,
            "labels": [label],
            "status": status,
            "issue_type": "Story",
            "priority": "Medium",
            "cloud_id": "c",
            "access_policy_id": "project:T2.0",
            "source_url": f"https://example.atlassian.net/browse/{key}",
            "issue_updated": "2026-09-11T10:00:00Z",
        },
    )


def test_jira_aggregate_uses_current_chunks_explicit_labels_and_stable_dedup() -> None:
    selection = select_providers("How many Jira tickets are labeled POS?", ENABLED)
    adapter = IndexedProviderAdapter(ProviderName.JIRA, "T2.0", _SnapshotRetriever())

    result = asyncio.run(adapter.aggregate(selection.structured_query))

    assert result.complete is True
    assert result.total == 1
    assert [row["key"] for row in result.rows] == ["T0-1"]
    assert result.snapshot_at == "2026-09-11T10:00:00Z"


def test_ticket_count_uses_structured_jira_route_without_repeating_provider_name() -> None:
    selection = select_providers("all tickets count?", (ProviderName.JIRA,))

    assert selection.mode == ExecutionMode.STRUCTURED
    assert selection.providers == (ProviderName.JIRA,)
    assert selection.structured_query is not None
    assert selection.structured_query.operation == StructuredOperation.COUNT


def test_status_followup_keeps_jira_scope_and_uses_stable_status_category() -> None:
    selection = select_providers("which is in progress", ENABLED, _scope(filters={}))

    assert selection.mode == ExecutionMode.STRUCTURED
    assert selection.structured_query is not None
    assert selection.structured_query.operation == StructuredOperation.LIST
    assert selection.structured_query.filters == {"status": ("In Progress",)}


def test_spanish_status_followup_is_structured() -> None:
    selection = select_providers("¿cuáles están en progreso?", ENABLED, _scope())

    assert selection.mode == ExecutionMode.STRUCTURED
    assert selection.structured_query is not None
    assert selection.structured_query.operation == StructuredOperation.LIST
    assert selection.structured_query.filters == {
        "labels": ("POS",),
        "status": ("In Progress",),
    }


def test_exact_issue_comment_and_detail_queries_bypass_semantic_search() -> None:
    comments = select_providers("Show comments on T0-13", ENABLED)
    detail = select_providers("What is the status of T0-13?", ENABLED)

    assert comments.structured_query is not None
    assert comments.structured_query.operation == StructuredOperation.SECTION
    assert comments.structured_query.section_kind == "COMMENT"
    assert comments.structured_query.filters["issue_key"] == ("T0-13",)
    assert detail.structured_query is not None
    assert detail.structured_query.operation == StructuredOperation.DETAIL


def test_project_lead_report_uses_complete_status_distribution() -> None:
    selection = select_providers("Give me a Jira status report", ENABLED)

    assert selection.structured_query is not None
    assert selection.structured_query.operation == StructuredOperation.DISTRIBUTION
    assert selection.structured_query.group_by == "status"


def test_in_progress_list_uses_current_snapshot_without_semantic_top_k() -> None:
    selection = select_providers("Which Jira tickets are in progress?", ENABLED)
    adapter = IndexedProviderAdapter(ProviderName.JIRA, "T2.0", _SnapshotRetriever())

    result = asyncio.run(adapter.aggregate(selection.structured_query))

    assert result.complete is True
    assert [row["key"] for row in result.rows] == ["T0-3"]


def test_comment_sections_are_grouped_by_event_identity() -> None:
    class SectionSnapshotRetriever:
        async def authorized_source_snapshot(self, source_types):
            assert source_types == ("ISSUE",)
            common = {
                "provider": "JIRA",
                "source_type": "ISSUE",
                "source_id": "jira:c:T0-13:COMMENT:42",
                "jira_chunk_kind": "COMMENT",
                "issue_key": "T0-13",
                "event_id": "42",
                "event_date": "2026-09-10T12:00:00Z",
                "event_author": "Developer",
                "cloud_id": "c",
                "access_policy_id": "project:T2.0",
                "source_url": "https://example.atlassian.net/browse/T0-13",
                "issue_updated": "2026-09-10T12:00:00Z",
            }
            return (
                (
                    Document(page_content="First half", metadata={**common, "chunk_ordinal": 0}),
                    Document(page_content="Second half", metadata={**common, "chunk_ordinal": 1}),
                ),
                True,
            )

    selection = select_providers("Show comments on T0-13", ENABLED)
    adapter = IndexedProviderAdapter(ProviderName.JIRA, "T2.0", SectionSnapshotRetriever())

    result = asyncio.run(adapter.aggregate(selection.structured_query))

    assert result.total == 1
    assert result.rows[0]["event_id"] == "42"
    assert result.rows[0]["text"] == "First half\nSecond half"


def test_jira_aggregate_accepts_issue_records_without_provider_metadata() -> None:
    class LegacySnapshotRetriever(_SnapshotRetriever):
        async def authorized_source_snapshot(self, source_types):
            documents, complete = await super().authorized_source_snapshot(source_types)
            for document in documents:
                document.metadata.pop("provider", None)
            return documents, complete

    retriever = LegacySnapshotRetriever()
    selection = select_providers("How many Jira tickets are labeled POS?", ENABLED)
    adapter = IndexedProviderAdapter(ProviderName.JIRA, "T2.0", retriever)

    result = asyncio.run(adapter.aggregate(selection.structured_query))

    assert result.complete is True
    assert result.total == 1


class _TruncatedRetriever(_SnapshotRetriever):
    async def authorized_source_snapshot(self, source_types):
        documents, _complete = await super().authorized_source_snapshot(source_types)
        return documents, False


def test_jira_aggregate_exposes_truncation_instead_of_claiming_completeness() -> None:
    selection = select_providers("How many tickets are in Jira?", ENABLED)
    adapter = IndexedProviderAdapter(ProviderName.JIRA, "T2.0", _TruncatedRetriever())

    result = asyncio.run(adapter.aggregate(selection.structured_query))

    assert result.complete is False
    assert result.degradation == ("SNAPSHOT_TRUNCATED",)


def _scope(**overrides) -> StructuredConversationScope:
    values = {
        "provider": "JIRA",
        "resourceType": "ISSUE",
        "filters": {"labels": ("POS",)},
        "operation": "COUNT",
        "complete": True,
        "pageSize": 50,
        "nextOffset": 0,
        "activeSubject": "Jira tickets matching POS",
    }
    values.update(overrides)
    return StructuredConversationScope(**values)


def test_jira_fixed_followup_inherits_provider_and_label_scope() -> None:
    selection = select_providers("what are all fixed?", ENABLED, _scope())

    assert selection.mode == ExecutionMode.STRUCTURED
    assert selection.reason == "JIRA_STRUCTURED_CONTEXT_INHERITED"
    assert selection.structured_query is not None
    assert selection.structured_query.operation == StructuredOperation.LIST
    assert selection.structured_query.filters == {
        "labels": ("POS",),
        "fixed": ("AUTO",),
    }


def test_explicit_status_semantics_replace_conflicting_inherited_status() -> None:
    fixed = select_providers(
        "what are all fixed?",
        ENABLED,
        _scope(filters={"labels": ("POS",), "status": ("To Do",)}),
    )
    todo = select_providers(
        "how many are To Do?",
        ENABLED,
        _scope(filters={"labels": ("POS",), "fixed": ("AUTO",)}),
    )

    assert fixed.structured_query.filters == {
        "labels": ("POS",),
        "fixed": ("AUTO",),
    }
    assert todo.structured_query.filters == {
        "labels": ("POS",),
        "status_category_key": ("new",),
    }


def test_jira_show_more_uses_saved_page_offset() -> None:
    selection = select_providers(
        "show more",
        ENABLED,
        _scope(operation="LIST", pageSize=25, nextOffset=50),
    )

    assert selection.structured_query is not None
    assert selection.structured_query.operation == StructuredOperation.LIST
    assert selection.structured_query.offset == 50
    assert selection.structured_query.limit == 25


def test_elliptical_label_change_replaces_inherited_label() -> None:
    selection = select_providers("what about BOT?", ENABLED, _scope())

    assert selection.structured_query is not None
    assert selection.structured_query.operation == StructuredOperation.COUNT
    assert selection.structured_query.filters == {"labels": ("BOT",)}


def test_explicit_provider_and_unrelated_topic_do_not_inherit_jira_scope() -> None:
    github = select_providers("What changed in GitHub?", ENABLED, _scope())
    unrelated = select_providers("How does cash reconciliation work?", ENABLED, _scope())

    assert github.mode == ExecutionMode.SINGLE_PROVIDER
    assert github.providers == (ProviderName.GITHUB,)
    assert unrelated.mode == ExecutionMode.LEGACY


def test_structured_followup_without_scope_requests_clarification() -> None:
    selection = select_providers("what are all fixed?", ENABLED)

    assert selection.mode == ExecutionMode.CLARIFICATION
    assert selection.reason == "STRUCTURED_CONTEXT_REQUIRED"


class _ResolutionSnapshotRetriever:
    def __init__(self, documents):
        self.documents = tuple(documents)

    async def authorized_source_snapshot(self, source_types):
        assert source_types == ("ISSUE",)
        return self.documents, True


def test_fixed_prefers_observed_resolution_and_keeps_numeric_issue_order() -> None:
    issue_10 = _issue("jira:c:T0-10:CURRENT", "T0-10", "Ten", "POS", "Done")
    issue_2 = _issue("jira:c:T0-2:CURRENT", "T0-2", "Two", "POS", "Done")
    issue_3 = _issue("jira:c:T0-3:CURRENT", "T0-3", "Three", "POS", "Done")
    issue_10.metadata["resolution"] = "Fixed"
    issue_2.metadata["resolution"] = "Fixed"
    issue_3.metadata["resolution"] = "Won't Do"
    adapter = IndexedProviderAdapter(
        ProviderName.JIRA, "T2.0", _ResolutionSnapshotRetriever([issue_10, issue_2, issue_3])
    )
    query = select_providers("what are all fixed?", ENABLED, _scope(pageSize=1)).structured_query

    result = asyncio.run(adapter.aggregate(query))

    assert result.total == 2
    assert [row["key"] for row in result.rows] == ["T0-2"]
    assert result.applied_filter_rule == "RESOLUTION:Fixed"
    assert len(result.evidence) == 1


def test_fixed_falls_back_to_done_status_category() -> None:
    done = _issue("jira:c:T0-1:CURRENT", "T0-1", "Done", "POS", "Closed")
    open_issue = _issue("jira:c:T0-2:CURRENT", "T0-2", "Open", "POS", "Working")
    done.metadata["status_category_key"] = "done"
    open_issue.metadata["status_category_key"] = "indeterminate"
    adapter = IndexedProviderAdapter(
        ProviderName.JIRA, "T2.0", _ResolutionSnapshotRetriever([done, open_issue])
    )
    query = select_providers("what are all fixed?", ENABLED, _scope()).structured_query

    result = asyncio.run(adapter.aggregate(query))

    assert result.total == 1
    assert result.applied_filter_rule == "STATUS_CATEGORY:DONE"


def test_fixed_uses_legacy_done_status_before_metadata_refresh() -> None:
    adapter = IndexedProviderAdapter(ProviderName.JIRA, "T2.0", _SnapshotRetriever())
    query = select_providers("what are all fixed?", ENABLED, _scope()).structured_query

    result = asyncio.run(adapter.aggregate(query))

    assert result.total == 1
    assert result.applied_filter_rule == "LEGACY_STATUS:DONE"


def test_multiple_fixed_equivalent_resolutions_require_clarification() -> None:
    fixed = _issue("jira:c:T0-1:CURRENT", "T0-1", "Fixed", "POS", "Done")
    resolved = _issue("jira:c:T0-2:CURRENT", "T0-2", "Resolved", "POS", "Done")
    fixed.metadata["resolution"] = "Fixed"
    resolved.metadata["resolution"] = "Resolved"
    adapter = IndexedProviderAdapter(
        ProviderName.JIRA, "T2.0", _ResolutionSnapshotRetriever([fixed, resolved])
    )
    query = select_providers("what are all fixed?", ENABLED, _scope()).structured_query

    result = asyncio.run(adapter.aggregate(query))

    assert result.clarification_options == ("Fixed", "Resolved")
    assert result.applied_filter_rule == "AMBIGUOUS_RESOLUTION"


def test_structured_jira_answer_returns_scope_and_page_for_backend_memory() -> None:
    class Workflow(ProviderNodesMixin):
        pass

    class Registry:
        def get(self, provider):
            assert provider == ProviderName.JIRA
            return IndexedProviderAdapter(ProviderName.JIRA, "T2.0", _SnapshotRetriever())

    workflow = Workflow()
    workflow._request = RagRequest(
        projectId="T2.0",
        collectionName="project-intelligence",
        question="List all Jira tickets for POS",
        accessPolicyIds=["project:T2.0"],
    )
    workflow._settings = SimpleNamespace(
        provider_timeout_seconds=2.0,
        provider_max_list_items=50,
    )
    workflow._provider_registry = Registry()
    selection = select_providers(workflow._request.question, ENABLED)

    state = asyncio.run(workflow._provider_execute({"provider_selection": selection}))

    response = state["provider_response"]
    assert response.conversation_context_update is not None
    scope = response.conversation_context_update.structured_scope
    assert scope is not None
    assert scope.provider == "JIRA"
    assert scope.filters == {"labels": ("POS",)}
    assert response.result_page is not None
    assert response.result_page.total == 1
    assert response.result_page.has_more is False


def test_chroma_document_mapping_preserves_jira_fixed_fields() -> None:
    from app.retrieval import ChromaAccessRetriever

    retriever = ChromaAccessRetriever.model_construct(
        index=None,
        collection_name="project-intelligence",
        text_field="chunk_text",
        project_id="T2.0",
        access_policy_ids=("project:T2.0",),
        required_schema_version="3",
        required_embedding_model="multilingual-e5-large",
        score_threshold=0.0,
    )
    document = retriever._document_from_fields(
        {
            "chunk_text": "Current Jira state",
            "project_id": "T2.0",
            "access_policy_id": "project:T2.0",
            "source_type": "ISSUE",
            "schema_version": "3",
            "embedding_model": "multilingual-e5-large",
            "status": "Done",
            "status_category": "Done",
            "status_category_key": "done",
            "resolution": "Fixed",
            "resolution_id": "10000",
        },
        "chunk-1",
        1.0,
    )

    assert document is not None
    assert document.metadata["status_category_key"] == "done"
    assert document.metadata["resolution"] == "Fixed"
    assert document.metadata["resolution_id"] == "10000"
