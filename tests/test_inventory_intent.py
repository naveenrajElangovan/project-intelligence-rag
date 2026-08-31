from app.workflow_support.inventory_intent import is_inventory_question
from app.config import Settings
from app.workflow_nodes.answering import (
    _evidence_population_members,
    _attribute_table_requested,
    _comparison_subjects,
    _coverage,
    _coverage_expected_identifiers,
    _deterministic_publisher_destination_answer,
    _deterministic_population_inventory_answer,
    _enforce_table_claim_shape,
    _note_coverage_shortfall,
    _population_labels,
    _population_source_ids,
    _publisher_destination_members,
    _published_population_members,
    _structured_tabular_evidence,
)
from app.table_evidence import normalize_table_dialect
from app.workflow_support.answer_structure import (
    AnswerLineKind,
    answer_shape_metrics,
    classify_answer_lines,
)
from app.llm import GroundedAnswer
from langchain_core.documents import Document


def test_detects_generic_inventory_requests() -> None:
    assert is_inventory_question("What are the shortcuts the POS application has?")
    assert is_inventory_question("Can you list all shortcuts in POS?")
    assert is_inventory_question("Show every configured integration")
    assert is_inventory_question("Which events are available?")
    assert is_inventory_question("Give me the supported values")
    assert is_inventory_question("What events does POS use?")
    assert is_inventory_question("What events does the POS application publish?")
    assert is_inventory_question("Which events does POS consume?")
    assert is_inventory_question("What POS events exist?")


def test_does_not_convert_single_item_questions_to_inventory() -> None:
    assert not is_inventory_question("What is POS_LOGIN?")
    assert not is_inventory_question("What are the fields of POS_EXTRACT_CASH?")
    assert not is_inventory_question("Which fields does POS_EXTRACT_CASH carry?")
    assert not is_inventory_question("How can I login to POS?")
    assert not is_inventory_question("Where is the receipt shortcut implemented?")
    assert not is_inventory_question("What version does the API use?")
    assert not is_inventory_question("Which file does this class live in?")


def test_bare_application_token_remains_an_inventory_scope() -> None:
    assert is_inventory_question("What events does POS use?")


def test_inventory_cross_encoder_pool_is_bounded_for_cpu_inference() -> None:
    settings = Settings()

    assert 4 <= settings.inventory_cross_encoder_candidate_limit <= 25
    assert settings.inventory_cross_encoder_candidate_limit < 50


def test_tabular_evidence_does_not_depend_on_planner_intent() -> None:
    documents = [
        Document(
            page_content="| Field | Type |\n|---|---|\n| id | string |",
            metadata={"doc_category": "narrative"},
        )
    ]

    assert _structured_tabular_evidence(documents)


def test_attribute_table_intent_does_not_include_procedural_wording() -> None:
    assert _attribute_table_requested("What are the payload fields of POS_CLOSE_SHIFT_REQUEST_EVENT?")
    assert _attribute_table_requested("Show the enum values")
    assert not _attribute_table_requested("How does a cashier close a shift?")


def test_comparison_requires_two_explicit_subjects() -> None:
    assert _comparison_subjects(
        "Compare POS_CLOSE_SHIFT_REQUEST_EVENT versus POS_EXTRACT_CASH fields",
        ("pos", "bot"),
    ) == ("POS_CLOSE_SHIFT_REQUEST_EVENT", "POS_EXTRACT_CASH")
    assert _comparison_subjects("Compare POS and BOT", ("pos", "bot")) == (
        "pos",
        "bot",
    )
    assert _comparison_subjects("Compare POS with its documentation", ("pos", "bot")) == ()


def test_table_shape_removes_uncited_prose_and_placeholder_rows() -> None:
    generated = GroundedAnswer(
        answer=(
            "| Attribute | POS | BOT |\n|---|---|---|\n"
            "| Version | 1 [SOURCE 1] | 2 [SOURCE 2] |\n"
            "| Owner | N/A [SOURCE 1] | Team [SOURCE 2] |\n\n"
            "This uncited summary must not veto the cited table."
        ),
        citations=[1, 2],
    )

    enforced, removed = _enforce_table_claim_shape(generated, "comparison_table")

    assert removed == 2
    assert "| Version |" in enforced.answer
    assert "| Owner |" not in enforced.answer
    assert "uncited summary" not in enforced.answer
    assert enforced.citations == [1, 2]


def test_population_labels_and_coverage_are_explicit() -> None:
    # Version and numeric labels still lead, and the requested member kind is now
    # carried too: without it a question about one kind of member ("all POS
    # shortcuts") matched every population in the project and the coverage
    # contract enumerated whichever one it was handed.
    # Both the written form and its singular stem are kept: stripping only the
    # suffix turned "libraries" into "librari", which matches neither "library"
    # nor "libraries" and dropped the subject the question was about.
    assert _population_labels("Give me all 1xx events for v0.4") == (
        "1xx",
        "v0.4",
        "events",
        "event",
    )
    assert _population_labels("list all libraries") == ("libraries", "library")
    assert _population_labels(
        "all BOT sending events?", ("pos", "bot")
    ) == ("events", "event", "sending", "send")
    assert _coverage(
        ("LOGIN_EVENT", "LOGOUT_EVENT"),
        "- LOGIN_EVENT is documented.",
    ) == ("LOGOUT_EVENT",)


def test_population_labels_exclude_the_application_name() -> None:
    """The loader filters by entity separately.

    One matching label admits a population, so keeping the application name as a
    label as well would match every population and undo the filter.
    """

    labels = _population_labels("can you give me all POS shortcuts?", ("pos", "bot"))
    assert labels == ("shortcuts", "shortcut")
    assert "pos" not in labels


def test_population_labels_distinguish_member_kinds() -> None:
    """A shortcuts question and an events question must not load the same population."""

    entities = ("pos", "bot")
    shortcuts = _population_labels("can you give me all POS shortcuts?", entities)
    events = _population_labels("what events does POS use?", entities)
    assert shortcuts != events
    assert "shortcut" in shortcuts and "event" not in shortcuts
    assert "event" in events and "shortcut" not in events


def test_partial_coverage_is_reported_without_replacing_the_answer() -> None:
    answer = GroundedAnswer(
        answer="LOGIN_EVENT is documented. [SOURCE 1]",
        citations=[1],
        missing_information=[],
    )

    reported = _note_coverage_shortfall(
        answer,
        ("LOGIN_EVENT", "LOGOUT_EVENT"),
        ("LOGOUT_EVENT",),
    )

    assert reported.answer == answer.answer
    assert reported.missing_information == [
        "1 of 2 identifiers confirmed; not confirmed: LOGOUT_EVENT."
    ]


def test_population_inventory_is_rendered_as_cited_identifier_bullets() -> None:
    documents = [
        Document(page_content=identifier, metadata={"entity_key": identifier})
        for identifier in ("POS_LOGIN", "POS_LOGOUT")
    ]

    answer = _deterministic_population_inventory_answer(
        ("POS_LOGIN", "POS_LOGOUT"), documents
    )

    assert answer is not None
    assert answer.answer == "- POS_LOGIN [SOURCE 1].\n- POS_LOGOUT [SOURCE 2]."
    assert answer.citations == [1, 2]


def _evidence(body: str, **metadata):
    return Document(page_content=body, metadata=metadata)


_SHORTCUT_TABLE = """## Keyboard shortcuts
| Key | Action | Condition |
| --- | --- | --- |
| F1 | Close the sale | main sales screen |
| F6 | Check price | requires open shift |
| F8 | Open cash drawer | home screen |
| Ctrl+B | Focus product search | shortcuts active |
| Ctrl+Q | Quick quantity | eligible product |
"""


def test_population_is_derived_from_enumerable_evidence() -> None:
    """Completeness must not depend on an ingestion-time category label.

    A page is labelled `registry-table` only when ingestion counts at least a
    fixed number of pipe rows. Below that literal the chunks carry no entity_key,
    no population formed, and an enumeration question was answered with whatever
    chunks arrived while nothing reported the omissions.
    """

    derived = _evidence_population_members([_evidence(_SHORTCUT_TABLE)])

    assert derived == ("F1", "F6", "F8", "Ctrl+B", "Ctrl+Q")


def test_prose_evidence_yields_no_population() -> None:
    """Only enumerable evidence may create a completeness contract."""

    prose = _evidence(
        "The application supports keyboard-driven operation. Cashiers close "
        "sales quickly and the drawer opens on request. Authentication "
        "establishes a session before any of this is possible."
    )

    assert _evidence_population_members([prose]) == ()


def test_metadata_population_takes_precedence_over_derived_members() -> None:
    labelled = _evidence("x", entity_key="ORDER_CREATED")

    assert _coverage_expected_identifiers(
        "give me all events", [labelled], [_evidence(_SHORTCUT_TABLE)]
    ) == ("ORDER_CREATED",)


_EVENT_POPULATION = [
    _evidence(
        f"| {name} | 1{index:02d} | wire key {name}_EVENT | published |",
        entity_key=name,
        title="Cross application event contract",
        structure_path=["POS event families"],
    )
    for index, name in enumerate(
        (
            "APP_CLIENT_RETURN_ITEMS",
            "APP_REQUEST_BULK_ITEM_SHRINKAGE",
            "APP_SALES_TICKET",
            "APP_SERVICE_TICKET",
            "APP_REQUEST_BULK_ITEM_TRANSFER",
        )
    )
]


def test_a_metadata_population_must_also_be_about_the_asked_subject() -> None:
    """The loader admits a chunk when *any* subject label matches it.

    One weak label is therefore enough to admit an entire unrelated registry --
    "key" matches every event row -- and this path used to return before any
    subject test ran, so the contract was built from those chunks and the answer
    enumerated them. Nothing here is about shortcuts, so no contract forms and
    the answer can report the absence.
    """

    for question in (
        "all the shortcut keys?",
        "i want all the shortcut keys",
        "can you give me all the shortcuts?",
    ):
        labels = _population_labels(question)
        assert (
            _coverage_expected_identifiers(
                question, _EVENT_POPULATION, _EVENT_POPULATION, labels
            )
            == ()
        ), question


def test_a_metadata_population_that_is_on_subject_still_forms() -> None:
    """A plural label matching nothing is not an absent subject.

    The labels carry both the written form and the singular stem, so "events"
    matching nothing while "event" matches every record is one word that is
    present -- not a reason to drop the contract.
    """

    for question in (
        "give me all the events",
        "list every event published",
        "what events exist?",
    ):
        labels = _population_labels(question)
        assert len(
            _coverage_expected_identifiers(
                question, _EVENT_POPULATION, _EVENT_POPULATION, labels
            )
        ) == 5, question


def test_derived_population_requires_an_inventory_question() -> None:
    assert _coverage_expected_identifiers(
        "what does F1 do?", [], [_evidence(_SHORTCUT_TABLE)]
    ) == ()


_ENVELOPE_SCHEMA = "| Field | Meaning |\n| --- | --- |\n" + "".join(
    f"| field{index} | description of field {index} |\n" for index in range(40)
)


def test_a_large_enumeration_forms_a_contract_over_every_member() -> None:
    """Size is not a reason to abandon completeness.

    A registry with many members is exactly the population an enumeration
    question asks for. Capping the contract -- at any number -- turns a complete
    answer into a silently partial one that nothing downstream can detect, so
    there is no ceiling and no floor: every member the source enumerates is in
    the contract.
    """

    derived = _evidence_population_members([_evidence(_ENVELOPE_SCHEMA)])

    assert derived == tuple(f"field{index}" for index in range(40))


def test_a_derived_population_is_rendered_in_full_without_the_generator() -> None:
    """No generation limit may decide how many members an answer prints.

    A population derived from evidence rows carries no entity_key, so the
    identifier-keyed renderer found nothing and the answer fell back to the
    generator, where the output token limit -- not the evidence -- decided the
    length. Rendering the located rows keeps every member and every column.
    """

    evidence = _evidence(_SHORTCUT_TABLE)
    expected = _evidence_population_members([evidence])

    rendered = _deterministic_population_inventory_answer(expected, [evidence])

    assert rendered is not None
    lines = rendered.answer.splitlines()
    assert len(lines) == len(expected)
    for identifier, line in zip(expected, lines):
        assert line.startswith(f"- {identifier} \u2014 ")
        assert line.endswith("[SOURCE 1].")
    assert "Close the sale" in lines[0]
    assert "main sales screen" in lines[0]


def test_repeated_member_rows_preserve_each_conditional_behavior() -> None:
    evidence = _evidence(
        "| Shortcut | Action | Condition |\n| --- | --- | --- |\n"
        "| F11 | Close shift | shift open |\n"
        "| F11 | Log out | no shift open |"
    )

    rendered = _deterministic_population_inventory_answer(("F11",), [evidence])

    assert rendered is not None
    assert "Close shift" in rendered.answer
    assert "shift open" in rendered.answer
    assert "Log out" in rendered.answer
    assert "no shift open" in rendered.answer


def test_a_large_derived_population_is_rendered_whole() -> None:
    evidence = _evidence(_ENVELOPE_SCHEMA)
    expected = _evidence_population_members([evidence])

    rendered = _deterministic_population_inventory_answer(expected, [evidence])

    assert rendered is not None
    assert len(expected) == 40
    assert len(rendered.answer.splitlines()) == 40


def test_an_unlocatable_member_still_falls_back_to_generation() -> None:
    """Strictness is unchanged: a member with no row does not get invented."""

    assert (
        _deterministic_population_inventory_answer(
            ("F1", "MISSING_MEMBER"), [_evidence(_SHORTCUT_TABLE)]
        )
        is None
    )


def test_a_two_row_registry_still_forms_a_contract() -> None:
    """No minimum either: a short registry is still a registry."""

    small = _evidence("| Key | Action |\n| --- | --- |\n| F1 | Close |\n| F6 | Price |\n")

    assert _evidence_population_members([small]) == ("F1", "F6")


def test_the_population_source_is_chosen_by_subject_not_by_size() -> None:
    """A source about a different population may not define the contract.

    Subject affinity replaces size as the selection rule: the off-subject
    registry loses even though it ranks first and enumerates more members.
    """

    off_subject = _evidence(
        "| Event | Meaning |\n| --- | --- |\n"
        + "".join(f"| EVENT_{index} | fired |\n" for index in range(12)),
        title="Kotlin event contract",
    )
    on_subject = _evidence(_SHORTCUT_TABLE, title="Keyboard shortcut reference")

    assert _evidence_population_members(
        [off_subject, on_subject], ("shortcut",)
    ) == ("F1", "F6", "F8", "Ctrl+B", "Ctrl+Q")
    # With no labels the retrieval ranking decides, as before.
    assert _evidence_population_members([off_subject, on_subject])[0] == "EVENT_0"


def test_registry_split_across_chunks_is_rendered_as_one_scoped_population() -> None:
    """A broad bilingual page title must not collapse or cross application scope."""

    shared = {
        "source_id": "page:shortcut-reference",
        "title": "POS and BOT Keyboard Shortcut Reference",
    }
    pos_first = _evidence(
        "| Shortcut | Action |\n| --- | --- |\n| F1 | Pay |\n| F2 | Direct pay |",
        **shared,
        structure_path=["POS shortcuts"],
    )
    bot = _evidence(
        "| Screen | Shortcut | Action |\n| --- | --- | --- |\n"
        "| Products | Ctrl+M | Shrinkage |\n| Cash | F6 | Expense |",
        **shared,
        structure_path=["BOT screen-specific controls"],
    )
    pos_second = _evidence(
        "| Shortcut | Action |\n| --- | --- |\n| Ctrl+A | Open shift |\n| F11 | Close shift |",
        **shared,
        structure_path=["POS shortcuts"],
    )

    assert _evidence_population_members(
        [bot, pos_first, pos_second],
        ("shortcuts", "shortcut", "keys", "key"),
        ("pos",),
    ) == ("F1", "F2", "Ctrl+A", "F11")
    assert _population_source_ids(
        [bot, pos_first, pos_second],
        ("shortcut", "keys", "key"),
        ("pos",),
    ) == ("page:shortcut-reference",)
    bot_prose = _evidence(
        "BOT handles shortcut help, but the help catalog omits some entries.",
        **shared,
        structure_path=["Known runtime differences"],
    )
    assert _population_source_ids(
        [bot_prose],
        ("shortcut", "keys", "key"),
        ("bot",),
    ) == ("page:shortcut-reference",)
    pos_cross_reference = _evidence(
        "| Shortcut | Action |\n| --- | --- |\n"
        "| Ctrl+E | BOT authorizes the request |",
        **shared,
        structure_path=["POS shortcuts"],
    )
    assert _evidence_population_members(
        [pos_cross_reference],
        ("shortcut", "keys", "key"),
        ("bot",),
    ) == ()


def test_sending_event_population_uses_publisher_status_not_family_name() -> None:
    family = _evidence(
        "| Constant | Wire name | APP | WORKER | Status |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| WORKER_SENT | WORKER_SENT | consumes | publishes | wired |\n"
        "| WORKER_RECEIVED | WORKER_RECEIVED | publishes | consumes | wired |\n"
        "| WORKER_UNUSED | WORKER_UNUSED | — | — | declared only |",
    )
    shared_family = _evidence(
        "| Constant | Wire name | APP | WORKER | Status |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| SHARED_REQUEST | SHARED_REQUEST | publishes | publishes | wired |",
    )

    assert _published_population_members(
        [family, shared_family], ("worker",)
    ) == ("WORKER_SENT", "SHARED_REQUEST")


def test_publisher_destination_population_is_partitioned_from_matrix_columns() -> None:
    matrix = _evidence(
        "| Event (wire name) | Publisher | Destinations | Consumer |\n"
        "| --- | --- | --- | --- |\n"
        "| APP_LOGIN | APP | Cloud only | none |\n"
        "| APP_LOCAL_REQUEST | APP | Worker only | Worker |\n"
        "| APP_SALE | APP | Worker + Cloud | Worker |\n"
        "| CLOUD_PROFILE | Cloud, and APP | district multicast | APP and Worker |\n"
        "| WORKER_REPLY | Worker | APP only | APP |",
    )

    assert _publisher_destination_members(
        [matrix], "app", ("worker", "cloud")
    ) == (
        "APP_LOCAL_REQUEST",
        "APP_LOGIN",
        "CLOUD_PROFILE",
        "APP_SALE",
    )
    generated = _deterministic_publisher_destination_answer(
        "List every event published by APP grouped by Worker only, Cloud only, and both",
        [matrix],
        "app",
        ("worker", "cloud"),
        "en",
    )
    assert generated is not None
    assert "### WORKER only (1)" in generated.answer
    assert "### CLOUD only (2)" in generated.answer
    assert "### Both WORKER and CLOUD (1)" in generated.answer
    assert "WORKER_REPLY" not in generated.answer


def test_a_generic_subject_word_alone_does_not_select_a_source() -> None:
    """Distinct-label counting is what makes a weak label harmless.

    Measured on the live corpus, "key" and "application" appear in the body of
    nine of ten sources, so any rule that admits on a single label match hands
    the contract to whichever off-subject registry ranks first.
    """

    off_subject = _evidence(
        "Every application key is documented here.\n"
        "| Event | Meaning |\n| --- | --- |\n"
        + "".join(f"| EVENT_{index} | fired |\n" for index in range(12)),
        title="Kotlin event contract",
    )
    on_subject = _evidence(_SHORTCUT_TABLE, title="POS keyboard shortcut keys")

    assert _evidence_population_members(
        [off_subject, on_subject], ("shortcut", "key", "application")
    ) == ("F1", "F6", "F8", "Ctrl+B", "Ctrl+Q")


def test_descriptive_table_cells_are_not_members() -> None:
    """A member is a name, not a description of a member.

    Accepting any short leading phrase collected column descriptions such as
    "Kotlin constant" and "Wire event name" from the live corpus as though they
    were registry members.
    """

    described = _evidence(
        "| Column | Meaning |\n| --- | --- |\n"
        "| Kotlin constant | the generated constant name |\n"
        "| Wire event name | the serialized event name |\n"
        "| Numeric event id | the stable numeric id |\n"
    )

    assert _evidence_population_members([described]) == ()


_CONFLUENCE_TABLE = """Key | Action | Condition
F1 | Close the sale | main sales screen
F6 | Check price | requires open shift
Ctrl+B | Focus product search | shortcuts active
Ctrl+Q | Quick quantity | eligible product
"""


def test_population_forms_from_a_page_table_without_a_markdown_separator() -> None:
    """A registry extracted from an HTML page has no separator row.

    Ingestion renders an HTML table row-wise as pipe-delimited cells, so the same
    registry that classifies as TABLE_ROW when it arrives as a document
    classifies as PROSE when it arrives as a page. Deriving members only from
    TABLE_ROW silently produced no contract for every page-sourced registry.
    """

    page_evidence = _evidence(normalize_table_dialect(_CONFLUENCE_TABLE))

    assert all(
        line.kind is not AnswerLineKind.PROSE
        for line in classify_answer_lines(page_evidence.page_content)
        if line.text.strip()
    )
    assert _evidence_population_members([page_evidence]) == (
        "F1",
        "F6",
        "Ctrl+B",
        "Ctrl+Q",
    )


def test_page_table_selects_structured_tabular_shape_and_reports_rows() -> None:
    page_evidence = _evidence(normalize_table_dialect(_CONFLUENCE_TABLE))

    assert _structured_tabular_evidence([page_evidence]) is True
    assert _attribute_table_requested("List every shortcut field and condition") is True
    metrics = answer_shape_metrics(page_evidence.page_content)
    assert metrics["answer_table_count"] == 1
    assert metrics["answer_table_rows"] == 4


def test_the_header_row_of_a_separatorless_table_is_not_a_member() -> None:
    """Without a separator there is no TABLE_HEADER, so position decides.

    A column name admitted as a member can never be covered, which would report
    every answer as incomplete.
    """

    derived = _evidence_population_members(
        [_evidence(normalize_table_dialect(_CONFLUENCE_TABLE))]
    )

    assert "Key" not in derived


def test_prose_containing_a_pipe_is_not_a_table() -> None:
    prose = _evidence(
        "Costs are split 60|40 between the teams. That ratio is fixed for now."
    )

    assert _evidence_population_members([prose]) == ()
