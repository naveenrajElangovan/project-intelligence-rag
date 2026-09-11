import pytest

from app.models import StructuredConversationScope
from app.providers.contracts import ExecutionMode, ProviderName, StructuredOperation
from app.providers.router import select_providers


ALL = (ProviderName.JIRA, ProviderName.GITHUB, ProviderName.CONFLUENCE)
JIRA_ONLY = (ProviderName.JIRA,)


@pytest.mark.parametrize(
    ("question", "enabled", "operation", "field", "value"),
    (
        ("all tickets count?", JIRA_ONLY, "COUNT", None, None),
        ("How many Jira issues exist?", ALL, "COUNT", None, None),
        ("¿Cuántos tickets hay en Jira?", ALL, "COUNT", None, None),
        (
            "Which Jira tickets are in progress?",
            ALL,
            "LIST",
            "status_category_key",
            "indeterminate",
        ),
        (
            "¿Cuáles tickets de Jira están en progreso?",
            ALL,
            "LIST",
            "status_category_key",
            "indeterminate",
        ),
        ("How many are done?", JIRA_ONLY, "COUNT", "status_category_key", "done"),
        ("¿Cuántos están completados?", JIRA_ONLY, "COUNT", "status_category_key", "done"),
        ("List open Jira tickets", ALL, "LIST", "status_category_key", "new"),
        ("Lista los tickets pendientes", JIRA_ONLY, "LIST", "status_category_key", "new"),
        ("Give me a Jira status report", ALL, "DISTRIBUTION", None, None),
        ("Dame un informe de estado de Jira", ALL, "DISTRIBUTION", None, None),
        ("Jira breakdown by issue type", ALL, "DISTRIBUTION", None, None),
        ("Desglose de Jira por prioridad", ALL, "DISTRIBUTION", None, None),
        ("Show high priority Jira bugs", ALL, "LIST", "issue_type", "Bug"),
        ("Muestra errores de Jira con prioridad alta", ALL, "LIST", "priority", "High"),
        ("Show blocked Jira tickets", ALL, "LIST", "status", "Blocked"),
        ("Muestra tickets bloqueados de Jira", ALL, "LIST", "status", "Blocked"),
        ("Show comments on T0-13", ALL, "SECTION", "section_kind", "COMMENT"),
        ("How many comments are in Jira?", ALL, "SECTION_COUNT", "section_kind", "COMMENT"),
        ("Muestra los comentarios de T0-13", ALL, "SECTION", "section_kind", "COMMENT"),
        ("What changed on T0-13?", ALL, "SECTION", "section_kind", "CHANGELOG"),
        ("¿Qué cambió en T0-13?", ALL, "SECTION", "section_kind", "CHANGELOG"),
        ("Show worklogs on T0-13", ALL, "SECTION", "section_kind", "WORKLOG"),
        ("Muestra registros de trabajo de T0-13", ALL, "SECTION", "section_kind", "WORKLOG"),
        ("List attachments on T0-13", ALL, "SECTION", "section_kind", "ATTACHMENT"),
        ("Lista los adjuntos de T0-13", ALL, "SECTION", "section_kind", "ATTACHMENT"),
        ("What dependencies block T0-13?", ALL, "SECTION", "section_kind", "RELATIONSHIP"),
        ("¿Qué dependencias bloquean T0-13?", ALL, "SECTION", "section_kind", "RELATIONSHIP"),
        ("Show acceptance criteria for T0-13", ALL, "SECTION", "section_kind", "ACCEPTANCE"),
        ("Muestra criterios de aceptación de T0-13", ALL, "SECTION", "section_kind", "ACCEPTANCE"),
        ("Show requirements for T0-13", ALL, "SECTION", "section_kind", "REQUIREMENTS"),
        ("Muestra los requisitos de T0-13", ALL, "SECTION", "section_kind", "REQUIREMENTS"),
        ("Show the description of T0-13", ALL, "SECTION", "section_kind", "DESCRIPTION"),
        (
            "Muestra los campos personalizados de T0-13",
            ALL,
            "SECTION",
            "section_kind",
            "CUSTOM_FIELD",
        ),
        ("Show external links for T0-13", ALL, "SECTION", "section_kind", "REMOTE_LINK"),
        ("What is the status of T0-13?", ALL, "DETAIL", "issue_key", "T0-13"),
        ("¿Quién está asignado a T0-13?", ALL, "DETAIL", "issue_key", "T0-13"),
        ("T0-13", ALL, "DETAIL", "issue_key", "T0-13"),
    ),
)
def test_project_lead_jira_intents_are_deterministic(question, enabled, operation, field, value):
    selection = select_providers(question, enabled)

    assert selection.mode == ExecutionMode.STRUCTURED
    assert selection.providers == (ProviderName.JIRA,)
    assert selection.structured_query is not None
    assert selection.structured_query.operation == StructuredOperation(operation)
    if field:
        assert value in selection.structured_query.filters[field]


@pytest.mark.parametrize(
    ("question", "expected_mode", "expected_providers"),
    (
        ("Is T0-13 implemented in GitHub?", "FEDERATED", (ProviderName.JIRA, ProviderName.GITHUB)),
        (
            "Compare Jira T0-13 with its Confluence requirements",
            "FEDERATED",
            (ProviderName.JIRA, ProviderName.CONFLUENCE),
        ),
        ("How does authentication work?", "LEGACY", ()),
        ("Why did the receipt ticket not print?", "LEGACY", ()),
        ("Show the Confluence documentation", "SINGLE_PROVIDER", (ProviderName.CONFLUENCE,)),
        ("Show the GitHub pull request status", "SINGLE_PROVIDER", (ProviderName.GITHUB,)),
    ),
)
def test_non_jira_and_federated_routes_keep_provider_boundaries(
    question, expected_mode, expected_providers
):
    selection = select_providers(question, ALL)

    assert selection.mode == ExecutionMode(expected_mode)
    assert selection.providers == expected_providers


def test_disabled_jira_fails_closed() -> None:
    selection = select_providers("What is the status of T0-13?", (ProviderName.GITHUB,))

    assert selection.mode == ExecutionMode.UNAVAILABLE
    assert selection.providers == (ProviderName.JIRA,)


@pytest.mark.parametrize(
    ("question", "operation", "field", "value"),
    (
        ("which is in progress", "LIST", "status_category_key", "indeterminate"),
        ("¿cuáles están en progreso?", "LIST", "status_category_key", "indeterminate"),
        ("how many are done?", "COUNT", "status_category_key", "done"),
        ("show comments", "SECTION", "section_kind", "COMMENT"),
        ("muestra el historial", "SECTION", "section_kind", "CHANGELOG"),
    ),
)
def test_project_lead_followups_inherit_jira_scope(question, operation, field, value):
    scope = StructuredConversationScope(
        provider="JIRA",
        filters={"labels": ("POS",)},
        operation="COUNT",
        complete=True,
        pageSize=20,
        nextOffset=20,
        activeSubject="Jira tickets matching POS",
    )

    selection = select_providers(question, ALL, scope)

    assert selection.mode == ExecutionMode.STRUCTURED
    assert selection.reason == "JIRA_STRUCTURED_CONTEXT_INHERITED"
    assert selection.structured_query.operation == StructuredOperation(operation)
    assert value in selection.structured_query.filters[field]
    assert selection.structured_query.filters["labels"] == ("POS",)
