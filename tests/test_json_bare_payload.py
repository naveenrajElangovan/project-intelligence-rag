"""A pasted document is a conversion request on its own. Requiring a trigger
phrase meant pasting JSON with no covering sentence did nothing at all."""

from app.workflow_support.json_transform import detect_json_transform_request


def _payload(question: str) -> str | None:
    detected = detect_json_transform_request(question, "en")
    return None if detected is None else detected.payload


def test_bare_object_is_converted_without_a_trigger_phrase():
    assert _payload('{"a": 1, "b": [2, 3]}') == '{"a": 1, "b": [2, 3]}'


def test_bare_array_is_converted():
    assert _payload("[1, 2, 3]") == "[1, 2, 3]"


def test_escaped_document_string_is_converted():
    assert _payload('"{\\"a\\": 1}"') is not None


def test_a_short_lead_in_still_counts_as_a_paste():
    assert _payload('here: {"a": 1}') == '{"a": 1}'


def test_a_real_question_containing_braces_is_not_hijacked():
    assert (
        _payload(
            "How does the POS build its catalog payload before it sends "
            '{"sku": 1} to the register?'
        )
        is None
    )


def test_prose_around_a_snippet_is_not_a_paste():
    assert (
        _payload(
            "I am debugging the terminal configuration flow and I keep seeing "
            'this shape {"terminalId": 4} in the logs, is that expected for a '
            "store that has not opened its shift yet?"
        )
        is None
    )


def test_a_fenced_block_alone_is_a_paste():
    assert _payload('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_a_fence_inside_a_question_is_not_a_paste():
    assert (
        _payload(
            "Is this the right request body for the ingestion endpoint, and does "
            'the worker validate it? ```json\n{"a": 1}\n```'
        )
        is None
    )


def test_a_trigger_phrase_still_works_with_surrounding_prose():
    assert (
        _payload('Please convert this to json for me: {"a": 1} thanks very much')
        == '{"a": 1}'
    )


def test_prose_with_no_payload_is_never_a_conversion():
    assert _payload("what does the bot application do?") is None


def test_empty_message_is_not_a_conversion():
    assert _payload("   ") is None


def test_invalid_bare_payload_still_reaches_the_parser_for_an_error():
    # A paste that cannot decode should report a parse error rather than being
    # silently routed into retrieval, where it would return no evidence.
    assert _payload("{'a': 1,}") == "{'a': 1,}"


def test_a_truncated_paste_is_recognised_as_json():
    """The repair existed; detection could not reach it.

    _widest_structural_span required a balanced span, so a payload cut before its
    closing bracket was never identified as JSON at all -- it fell through to
    retrieval and came back as an answer about the project, which is what made a
    truncated paste look like a corpus problem.
    """

    payload = _payload('{"event": "POS_CLOSE_SHIFT_REQUEST", "fields": [{"wire": "close_amount_cents"')

    assert payload is not None
    assert payload.startswith('{"event"')


def test_a_truncated_array_paste_is_recognised():
    assert _payload('["a", "b') is not None


def test_prose_containing_an_unbalanced_brace_is_not_hijacked():
    # The span only runs to the end of the text when nothing precedes it, so a
    # sentence that happens to contain a stray brace stays a question.
    assert _payload("How does the POS build {\"sku\": 1 before sending it?") is None
