"""Project vocabulary prevents planning source families that cannot exist."""

import pytest

from app.models import RagRequest
from app.workflow_nodes.planning import _narrow_source_types
from app.workflow_support.fail_closed import clarification_response
from app.workflow_support.query_analysis import _source_route_intent


STORE_DELIVERY_WORDS = (
    "¿Cómo hago entrega de valores?",
    "¿Cómo filtro prioridad?",
    "¿Dónde veo el estado del ticket?",
    "¿Qué hago con los errores de la impresora?",
    "¿Cómo registro la entrega de mercancía?",
    "What is the status of the delivery?",
)


@pytest.mark.parametrize("question", STORE_DELIVERY_WORDS)
def test_documentation_only_projects_do_not_route_store_words_to_jira(
    question: str,
) -> None:
    assert _source_route_intent(question, ("PAGE",)) != "DELIVERY"
    assert _source_route_intent(question, ("PAGE", "CODE", "ISSUE")) == "DELIVERY"


def test_project_vocabulary_can_reassign_an_overloaded_intent_term() -> None:
    terms = {
        "DELIVERY": ("jira", "issue", "sprint"),
        "IMPLEMENTATION": ("entrega",),
        "CROSS_SOURCE": (),
    }
    assert _source_route_intent(
        "Explica la entrega", ("PAGE", "CODE", "ISSUE"), terms
    ) == "IMPLEMENTATION"
    assert _source_route_intent(
        "Explica la entrega", ("PAGE", "CODE", "ISSUE")
    ) == "DELIVERY"


def test_explicit_jira_request_needs_an_issue_source() -> None:
    question = "show me the open jira issues"
    assert _source_route_intent(question, ("PAGE", "CODE", "ISSUE")) == "DELIVERY"
    assert _source_route_intent(question, ("PAGE",)) != "DELIVERY"


@pytest.mark.parametrize("question", STORE_DELIVERY_WORDS + ("Give me APP-42 details",))
def test_unobserved_vocabulary_keeps_existing_delivery_routing(question: str) -> None:
    assert _source_route_intent(question, ()) == "DELIVERY"


def test_source_scope_is_intersected_without_creating_an_empty_filter() -> None:
    assert _narrow_source_types(("PAGE", "CODE"), ("PAGE",)) == ("PAGE",)
    assert _narrow_source_types(("PAGE", "CODE"), ()) == ("PAGE", "CODE")
    assert _narrow_source_types(("CODE",), ("PAGE",)) == ()


@pytest.mark.parametrize(
    "question",
    ("show me the open jira issues", "give me the SQL database commands"),
)
def test_documentation_only_project_refuses_developer_sources_before_retrieval(
    question: str,
) -> None:
    request = RagRequest(
        projectId="T2.0-STORE",
        collectionName="project-intelligence",
        question=question,
        accessPolicyIds=["project:T2.0-STORE"],
    )

    response = clarification_response(request, ("pos", "bot"), ("PAGE",))

    assert response is not None
    assert response.status == "INSUFFICIENT_EVIDENCE"
    assert response.confidence == "NONE"
    assert response.sources == []
    assert response.failure_reason == "SOURCE_SCOPE_VIOLATION"
