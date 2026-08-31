"""Indent-only output put every scalar on its own line, so a document with a few
hundred keys became a few hundred lines -- unreadable and painful to select."""

import json

from app.workflow_support.json_transform import (
    LINE_WIDTH,
    format_json,
    transform_json,
)


def _lines(text: str) -> list[str]:
    return text.splitlines()


def test_no_line_exceeds_the_target_width_for_ordinary_content():
    payload = {
        "shortcuts": [f"shortcut{index}" for index in range(60)],
        "events": [{"id": index, "name": f"Event{index}"} for index in range(20)],
    }
    for line in _lines(format_json(payload)):
        assert len(line) <= LINE_WIDTH, line


def test_a_small_document_stays_on_one_line():
    assert format_json({"a": 1, "b": [2, 3]}) == '{"a": 1, "b": [2, 3]}'


def test_a_scalar_array_is_packed_across_the_width_not_down_the_page():
    payload = {"names": [f"name{index}" for index in range(40)]}
    rendered = format_json(payload)
    assert len(_lines(rendered)) < 12
    assert json.loads(rendered) == payload


def test_output_is_far_shorter_than_indent_only_output():
    payload = {f"key_{index}": index for index in range(200)}
    filled = len(_lines(format_json(payload)))
    indented = len(_lines(json.dumps(payload, indent=2)))
    assert filled * 4 < indented


def test_formatting_always_round_trips():
    payload = {
        "nested": {"deep": {"deeper": [1, 2, {"x": None, "y": True}]}},
        "unicode": "configuración de terminal",
        "empty_object": {},
        "empty_array": [],
        "long_string": "x" * 300,
    }
    assert json.loads(format_json(payload)) == payload


def test_a_string_longer_than_the_width_is_not_broken():
    # Breaking inside a string literal would change the value.
    rendered = format_json({"note": "y" * 400})
    assert json.loads(rendered) == {"note": "y" * 400}
    assert len(max(_lines(rendered), key=len)) > LINE_WIDTH


def test_mixed_objects_keep_key_order_across_packed_and_expanded_pairs():
    payload = {
        "first": 1,
        "second": 2,
        "block": {f"inner_{index}": "x" * 20 for index in range(20)},
        "third": 3,
    }
    rendered = format_json(payload)
    assert list(json.loads(rendered)) == ["first", "second", "block", "third"]


def test_the_transformer_uses_the_filled_formatter():
    result = transform_json('{"a":1,"b":2}')
    assert result.ok
    assert result.text == '{"a": 1, "b": 2}'


def test_deep_nesting_still_indents_readably():
    payload = {"a": {"b": {"c": {"d": [f"value{index}" for index in range(30)]}}}}
    rendered = format_json(payload)
    assert json.loads(rendered) == payload
    assert any(line.startswith("        ") for line in _lines(rendered))
