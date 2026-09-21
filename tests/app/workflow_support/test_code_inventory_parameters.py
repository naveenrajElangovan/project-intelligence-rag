import asyncio

import pytest
from langchain_core.documents import Document

from app import workflow as workflow_module
from app.config import Settings
from app.llm import GroundedAnswer
from app.models import RagRequest
from app.vocabulary import CorpusVocabulary
from app.workflow_support.conversation import (
    _conversation_resolution_decision,
    _deterministic_conversation_rewrite,
    build_conversation_context_update,
)
from app.workflow_support.deterministic_answers import (
    _code_inventory_documents,
    _code_inventory_answer_verified,
    _deterministic_code_inventory_answer,
    _deterministic_structured_inventory_answer,
)
from app.workflow_support.inventory_intent import is_exhaustive_entity_detail_question
from app.workflow_support.query_analysis import _code_inventory_requested


def _code(path: str, symbol: str, content: str = "") -> Document:
    return Document(
        page_content=content or f"class {symbol}",
        metadata={
            "source_type": "CODE",
            "repository": "store-core-kotlin",
            "branch": "main",
            "path": path,
            "symbol": symbol,
        },
    )


def test_same_file_chunks_are_grouped_by_distinct_symbols() -> None:
    documents = [
        _code("src/EventType.kt", "LOGIN_POS_EVENT"),
        _code("src/EventType.kt", "BOT_SEND_FILE"),
        _code("src/EventType.kt", "BOT_SEND_FILE"),
    ]

    answer = _deterministic_code_inventory_answer(documents, "en")

    assert answer is not None
    assert answer.answer.count("src/EventType.kt") == 1
    assert answer.answer.count("BOT_SEND_FILE") == 1
    assert "LOGIN_POS_EVENT" in answer.answer
    assert answer.citations == [1, 2, 3]
    assert _code_inventory_answer_verified(answer, documents)


@pytest.mark.parametrize(
    "symbol",
    [
        "BOT_SEND_FILE",
        "IOT_TPV_CONFIGURATION_RESPONSE",
        "ANDROID_UNIT_TEST_PATH",
        "COMMON_MAIN_PATH",
        "PACKAGE_TASK_FILE",
        "MODULE_PATH",
    ],
)
def test_entity_name_fragments_do_not_trigger_code_inventory(symbol: str) -> None:
    assert not _code_inventory_requested(f"Give me all parameters for {symbol}")


@pytest.mark.parametrize(
    "symbol",
    [
        "AirTimeModalFocusConfig",
        "AuthenticationModalFocusConfig",
        "PaymentMethod",
        "ProductPackage",
        "WindowConfig",
    ],
)
def test_real_field_bearing_symbols_classify_like_other_parameter_requests(
    symbol: str,
) -> None:
    assert not _code_inventory_requested(f"Give me all parameters for {symbol}", (symbol,))


@pytest.mark.parametrize(
    "question",
    [
        "list all the files in this module",
        "show me every class in this package",
        "List all files referenced by BOT_SEND_FILE",
    ],
)
def test_genuine_code_inventory_requests_still_trigger(question: str) -> None:
    assert _code_inventory_requested(question, ("BOT_SEND_FILE",))


@pytest.mark.parametrize(
    "symbol",
    [
        "BOT_SEND_FILE",
        "IOT_TPV_CONFIGURATION_RESPONSE",
        "ANDROID_UNIT_TEST_PATH",
        "COMMON_MAIN_PATH",
        "PACKAGE_TASK_FILE",
        "MODULE_PATH",
    ],
)
def test_first_turn_parameter_request_for_code_named_symbol_routes_to_structured_details(
    symbol: str,
) -> None:
    question = f"{symbol} send me all the parameters needed for this"
    request = RagRequest(
        projectId="T2.0",
        collectionName="project-intelligence",
        question=question,
        accessPolicyIds=["project:T2.0"],
    )
    workflow = workflow_module.AuthorizedRagWorkflow.__new__(workflow_module.AuthorizedRagWorkflow)
    workflow._request = request
    workflow._settings = Settings(_env_file=None, environment="development")
    workflow._vocabulary = CorpusVocabulary(
        entities=(symbol,), source_types=("PAGE", "CODE", "ISSUE")
    )

    planned = asyncio.run(workflow._plan_queries({"request": request}))

    assert planned["query_intent"] == "STRUCTURED_ENTITY"
    assert planned["resolved_question"] == question
    assert all(symbol in query for query in planned["queries"])


def test_same_file_chunks_without_symbols_fail_closed() -> None:
    documents = [
        _code("src/Unknown.kt", "", "first undifferentiated fragment"),
        _code("src/Unknown.kt", "", "second undifferentiated fragment"),
    ]

    assert _deterministic_code_inventory_answer(documents, "en") is None


def test_different_files_without_symbols_also_fail_closed() -> None:
    documents = [
        _code("src/One.kt", "", "first undifferentiated fragment"),
        _code("src/Two.kt", "", "second undifferentiated fragment"),
    ]

    assert _deterministic_code_inventory_answer(documents, "en") is None


def test_code_parameter_followup_prefers_identifier_from_grounded_assistant_turn() -> None:
    history = [
        ("user", "What event is used to send a file?"),
        ("assistant", "The event is `BOT_SEND_FILE` and is grounded in the registry."),
    ]

    rewritten = _deterministic_conversation_rewrite(
        "Give me the parameters or fields required for this event.", history, "en"
    )

    assert rewritten is not None
    assert rewritten.endswith("(previous subject: BOT_SEND_FILE)")


@pytest.mark.parametrize(
    "question",
    [
        "not the file names, the parameters instead",
        "I mean the required fields, not the file names",
        "just the parameters please",
        "i need the parameterds rquired not the files names",
    ],
)
def test_corrective_attribute_request_is_a_followup(question: str) -> None:
    assert _conversation_resolution_decision(question, ("BOT_SEND_FILE",)) == (
        True,
        "CORRECTIVE_ATTRIBUTE_FOLLOWUP",
    )


def test_correction_with_a_genuinely_new_topic_stays_standalone() -> None:
    assert _conversation_resolution_decision(
        "I mean refunds, not payments", ("BOT_SEND_FILE",)
    ) == (False, "EXPLICIT_SUBJECT")


@pytest.mark.parametrize("subject", ["BOT_SEND_FILE", "POS_START_SHIFT_EVENT"])
@pytest.mark.parametrize(
    "question",
    [
        "not the file names, the parameters instead",
        "I mean the required fields, not the file names",
        "just the parameters please",
    ],
)
def test_corrective_followup_preserves_and_rewrites_the_active_code_subject(
    subject: str, question: str
) -> None:
    request = RagRequest(
        projectId="T2.0",
        collectionName="project-intelligence",
        question=question,
        accessPolicyIds=["project:T2.0"],
        conversationHistory=[
            {"role": "user", "content": f"Show me {subject}."},
            {"role": "assistant", "content": f"The active code entity is `{subject}`."},
        ],
        conversationContext={"activeSubject": subject, "stateRevision": 1},
    )
    workflow = workflow_module.AuthorizedRagWorkflow.__new__(workflow_module.AuthorizedRagWorkflow)
    workflow._request = request
    workflow._settings = Settings(_env_file=None, environment="development")
    workflow._vocabulary = CorpusVocabulary(entities=(subject,))

    resolved = asyncio.run(workflow._resolve_conversation_question(question, "en"))
    update = workflow._conversation_context_update(
        {"resolved_question": resolved, "query_intent": "CODE_INVENTORY"}
    )

    assert resolved.startswith(f"Regarding {subject}: What are the ")
    assert resolved.endswith(f"Clarification: {question}")
    assert update.standalone_question == resolved
    assert update.active_subject == subject


def test_corrective_parameter_followup_keeps_retrieval_queries_on_the_active_entity() -> None:
    question = "i need the parameterds rquired not the files names"
    request = RagRequest(
        projectId="T2.0",
        collectionName="project-intelligence",
        question=question,
        accessPolicyIds=["project:T2.0"],
        conversationHistory=[
            {
                "role": "user",
                "content": "BOT_SEND_FILE send me all the parameters needed for this",
            },
            {
                "role": "assistant",
                "content": "BOT_SEND_FILE is the active code entity.",
            },
        ],
        conversationContext={"activeSubject": "BOT_SEND_FILE", "stateRevision": 1},
    )
    workflow = workflow_module.AuthorizedRagWorkflow.__new__(workflow_module.AuthorizedRagWorkflow)
    workflow._request = request
    workflow._settings = Settings(_env_file=None, environment="development")
    workflow._vocabulary = CorpusVocabulary(
        entities=("BOT_SEND_FILE",), source_types=("PAGE", "CODE", "ISSUE")
    )

    planned = asyncio.run(workflow._plan_queries({"request": request}))

    assert planned["resolved_question"] == (
        f"Regarding BOT_SEND_FILE: What are the parameters? Clarification: {question}"
    )
    assert planned["query_intent"] == "STRUCTURED_ENTITY"
    assert all("BOT_SEND_FILE" in query for query in planned["queries"])


def test_grounded_code_identifier_becomes_the_active_subject() -> None:
    request = RagRequest(
        projectId="T2.0",
        collectionName="project-intelligence",
        question="What event is used to send a file?",
        accessPolicyIds=["project:T2.0"],
    )
    state = {
        "resolved_question": request.question,
        "query_intent": "IMPLEMENTATION",
        "generated": GroundedAnswer(
            answer="The event is `BOT_SEND_FILE` [SOURCE 1].", citations=[1]
        ),
        "documents": [
            Document(
                page_content='BOT_SEND_FILE("BOT_SEND_FILE", 224, "0.1")',
                metadata={"entity_key": "BOT_SEND_FILE", "symbol": "BOT_SEND_FILE"},
            )
        ],
    }

    update = build_conversation_context_update(request, state, ("bot", "pos"))

    assert update.active_subject == "BOT_SEND_FILE"
    assert update.entities[0].canonical_value == "BOT_SEND_FILE"


def test_plural_field_followup_is_an_exhaustive_entity_detail_request() -> None:
    assert is_exhaustive_entity_detail_question(
        "Give me the parameters or fields required for this event. "
        "(previous subject: POS_PAYMENT_TRANSACTION_EVENT)"
    )


def test_structured_event_uses_enum_metadata_not_an_unrelated_routing_table() -> None:
    documents = [
        Document(
            page_content='POS_PAYMENT_TRANSACTION_EVENT("POS_PAYMENT_TRANSACTION", 115, "0.1"),',
            metadata={"entity_key": "POS_PAYMENT_TRANSACTION_EVENT"},
        ),
        Document(
            page_content=(
                "| Event | Publisher | Destinations | Consumer |\n"
                "| POS_PAYMENT_TRANSACTION | TPV | Solo IoT | none |"
            ),
            metadata={},
        ),
    ]

    answer = _deterministic_structured_inventory_answer(
        "Which entry represents POS_PAYMENT_TRANSACTION?", documents, "en"
    )

    assert answer is not None
    assert "POS_PAYMENT_TRANSACTION_EVENT" in answer.answer
    assert "numeric event id 115" in answer.answer
    assert "TPV" not in answer.answer


def test_structured_event_collects_individual_field_metadata_chunks() -> None:
    documents = [
        Document(
            page_content='POS_PAYMENT_TRANSACTION_EVENT("POS_PAYMENT_TRANSACTION", 115, "0.1"),',
            metadata={"entity_key": "POS_PAYMENT_TRANSACTION_EVENT"},
        ),
        Document(
            page_content='@SerialName("region_id") val regionId: String,',
            metadata={
                "chunk_profile": "data-class-field",
                "entity_key": "POS_PAYMENT_TRANSACTION",
                "serialized_field": "region_id",
                "field_name": "regionId",
                "field_type": "String",
            },
        ),
        Document(
            page_content='@SerialName("ticket_uuid") val ticketUuid: String,',
            metadata={
                "chunk_profile": "data-class-field",
                "entity_key": "POS_PAYMENT_TRANSACTION",
                "serialized_field": "ticket_uuid",
                "field_name": "ticketUuid",
                "field_type": "String",
            },
        ),
    ]

    answer = _deterministic_structured_inventory_answer(
        "Give all POS_PAYMENT_TRANSACTION_EVENT fields", documents, "en"
    )

    assert answer is not None
    assert "region_id" in answer.answer
    assert "ticket_uuid" in answer.answer


def test_code_inventory_filters_to_the_exact_requested_path_even_without_symbols() -> None:
    documents = [
        _code(".github/workflows/workflow.yml", "", "name: Workflow"),
        _code("src/Unrelated.kt", "Unrelated"),
    ]

    selected = _code_inventory_documents(
        documents,
        25,
        "List all classes and functions in .github/workflows/workflow.yml",
    )

    assert [document.metadata["path"] for document in selected] == [
        ".github/workflows/workflow.yml"
    ]


def test_code_inventory_does_not_expand_build_file_to_other_gradle_scripts() -> None:
    documents = [
        _code("build-logic/build.gradle.kts", "", "plugins {}"),
        _code("build-logic/src/main/kotlin/secrets.gradle.kts", "getProperties"),
    ]

    selected = _code_inventory_documents(
        documents,
        25,
        "List all classes and functions in build-logic/build.gradle.kts",
    )

    assert [document.metadata["path"] for document in selected] == ["build-logic/build.gradle.kts"]


def test_resolved_enum_identifier_wins_over_wire_name_for_active_subject() -> None:
    request = RagRequest(
        projectId="T2.0",
        collectionName="project-intelligence",
        question="Give me the parameters or fields required for this event.",
        accessPolicyIds=["project:T2.0"],
    )
    state = {
        "resolved_question": (
            "Give me the parameters or fields required for this event. "
            "(previous subject: POS_START_SHIFT_EVENT)"
        ),
        "query_intent": "STRUCTURED_ENTITY",
        "generated": GroundedAnswer(
            answer="The `POS_START_SHIFT` contract uses wire name `POS_START_SHIFT`.",
            citations=[1],
        ),
        "documents": [
            Document(
                page_content='POS_START_SHIFT_EVENT("POS_START_SHIFT", 103, "0.2")',
                metadata={"entity_key": "POS_START_SHIFT_EVENT"},
            )
        ],
    }

    update = build_conversation_context_update(request, state, ("pos", "shift"))

    assert update.active_subject == "POS_START_SHIFT_EVENT"
