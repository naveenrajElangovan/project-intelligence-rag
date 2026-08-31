"""Deterministic JSON conversion: detection, repair, bounds, and non-interference."""

import json

import pytest

from app.workflow_support.json_transform import (
    MAX_NESTING_DEPTH,
    MAX_PAYLOAD_CHARACTERS,
    detect_json_transform_request,
    json_transform_answer,
    transform_json,
)


def _converted(message: str, language: str = "en") -> str:
    detected = detect_json_transform_request(message, language)
    assert detected is not None, message
    result = transform_json(detected.payload)
    assert result.ok, result.error_message
    # Anything reported as converted must itself be strict, parseable JSON.
    json.loads(result.text)
    return result.text


def test_valid_json_is_formatted_with_key_order_preserved() -> None:
    text = _converted('convert to json: {"b":1,"a":{"d":true,"c":[1,2]}}')
    assert list(json.loads(text)) == ["b", "a"]
    # This used to assert indented output. Formatting now fills the line width,
    # so a document this small is deliberately one line; indentation appears only
    # where a subtree does not fit. Key order and round-tripping are the parts
    # that were ever worth pinning.
    assert json.loads(text) == {"b": 1, "a": {"d": True, "c": [1, 2]}}


def test_a_document_too_wide_for_one_line_is_indented() -> None:
    text = _converted(
        "convert to json: "
        + json.dumps({"outer": {f"key_{index}": "x" * 20 for index in range(20)}})
    )
    assert "\n  " in text


def test_doubly_encoded_json_string_becomes_an_object() -> None:
    payload = json.dumps(json.dumps({"event": "POS_CLOSE_SHIFT_EVENT", "amount": 1250}))
    detected = detect_json_transform_request(
        "convert this to json object: " + payload, "en"
    )
    assert detected is not None
    result = transform_json(detected.payload)
    assert result.ok
    assert result.unwrap_rounds == 1
    assert json.loads(result.text)["event"] == "POS_CLOSE_SHIFT_EVENT"


def test_repeatedly_encoded_json_string_unwraps_every_level() -> None:
    payload = json.dumps(json.dumps(json.dumps({"a": 1})))
    detected = detect_json_transform_request("convert to json object: " + payload, "en")
    assert detected is not None
    result = transform_json(detected.payload)
    assert result.ok
    assert result.unwrap_rounds == 2
    assert json.loads(result.text) == {"a": 1}


def test_an_ordinary_string_value_is_not_unwrapped() -> None:
    assert json.loads(_converted('convert to json {"greet":"hello"}')) == {
        "greet": "hello"
    }


def test_a_quoted_object_inside_a_valid_object_stays_a_string() -> None:
    value = json.loads(_converted('convert to json {"a": "{\\"x\\":1}", "b": 2}'))
    assert value["a"] == '{"x":1}'
    assert value["b"] == 2


def test_fenced_payload_is_preferred_over_surrounding_prose() -> None:
    message = 'format json\n```json\n{"a": 1,}\n```\nthanks'
    assert json.loads(_converted(message)) == {"a": 1}


@pytest.mark.parametrize(
    ("message", "repair", "expected"),
    [
        ('fix this json {"a":1,"b":2,}', "trailing_commas", {"a": 1, "b": 2}),
        ("convert to json {'t':'T-1'}", "single_quotes", {"t": "T-1"}),
        (
            'convert to json {"ok":True,"bad":False,"m":None}',
            "python_literals",
            {"ok": True, "bad": False, "m": None},
        ),
        ("convert to json {folio: 12}", "unquoted_keys", {"folio": 12}),
        ('format json {\n // note\n "id": 7\n}', "comments", {"id": 7}),
        (
            'convert to json {"x":NaN,"y":Infinity}',
            "non_finite_numbers",
            {"x": None, "y": None},
        ),
        ("convert to json {\u201ca\u201d:\u201cb\u201d}", "smart_quotes", {"a": "b"}),
        (
            'convert to json {"a":1}{"b":2}',
            "concatenated_objects",
            [{"a": 1}, {"b": 2}],
        ),
    ],
)
def test_each_repair_is_applied_and_named(
    message: str, repair: str, expected: object
) -> None:
    detected = detect_json_transform_request(message, "en")
    assert detected is not None
    result = transform_json(detected.payload)
    assert result.ok, result.error_message
    assert repair in result.repairs
    assert json.loads(result.text) == expected


def test_top_level_array_is_not_reduced_to_a_nested_object() -> None:
    assert json.loads(_converted('convert to json [1,2,{"a":3},]')) == [1, 2, {"a": 3}]


def test_braces_inside_a_string_do_not_truncate_the_payload() -> None:
    assert json.loads(_converted('convert to json {"tpl":"a{b}c","n":1}')) == {
        "tpl": "a{b}c",
        "n": 1,
    }


def test_accented_spanish_content_is_not_escaped() -> None:
    text = _converted('convertir a json {"d":"Devolución de artículos"}', "es")
    assert "Devolución de artículos" in text
    assert "\\u" not in text


def test_unparseable_input_reports_a_position_and_is_returned_unchanged() -> None:
    detected = detect_json_transform_request('convert to json {"a": }', "en")
    assert detected is not None
    result = transform_json(detected.payload)
    assert not result.ok
    assert result.error_line >= 1
    assert result.error_column >= 1
    assert result.text == '{"a": }'


def test_failure_is_reported_in_spanish_for_a_spanish_request() -> None:
    result = transform_json('{"a": }')
    answer = json_transform_answer(result, "es")
    assert "No pude convertir" in answer
    assert "línea" in answer


def test_oversized_payload_is_refused_rather_than_processed() -> None:
    result = transform_json("[" + "1," * MAX_PAYLOAD_CHARACTERS + "1]")
    assert not result.ok
    assert "limit" in result.error_message


def test_excessive_nesting_is_refused() -> None:
    depth = MAX_NESTING_DEPTH + 5
    result = transform_json("[" * depth + "]" * depth)
    assert not result.ok
    assert "levels deep" in result.error_message


@pytest.mark.parametrize(
    "question",
    [
        "How does the POS build its JSON catalog?",
        "What json object does POS_SALES_TICKET_EVENT carry?",
        "Which module owns the close-shift flow?",
        "convert to json",
        "explain the json converter feature",
        "¿Cómo se formatea el json del ticket?",
        "¿Qué eventos IoT publica el POS?",
    ],
)
def test_project_questions_still_route_to_retrieval(question: str) -> None:
    """A trigger phrase without a payload, or a payload without a request, is not ours."""

    assert detect_json_transform_request(question, "en") is None
    assert detect_json_transform_request(question, "es") is None
