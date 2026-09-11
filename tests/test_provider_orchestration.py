import asyncio

from langchain_core.documents import Document

from app.providers.contracts import ExecutionMode, ProviderName, StructuredOperation
from app.providers.indexed import IndexedProviderAdapter
from app.providers.router import select_providers


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
                Document(
                    page_content="historical",
                    metadata={"provider": "JIRA", "jira_chunk_kind": "CHANGELOG", "issue_key": "T0-1"},
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
