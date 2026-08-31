"""Truncation is the most common way JSON arrives broken -- a log line cut at a
column limit, a console pane that scrolled, a half-selected block -- and the most
mechanically fixable, because the open structure is known exactly.

What must never happen is inventing content to close it. A dangling key or a
partial string is dropped, not filled with null, because a fabricated field in a
payload the user is about to trust is worse than a shorter payload.
"""

import json

import pytest

from app.workflow_support.json_transform import transform_json


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"a": 1, "b": 2', {"a": 1, "b": 2}),
        ('{"a": 1, "b": [2, 3', {"a": 1, "b": [2, 3]}),
        ('{"a": 1, "b": {"c": 4', {"a": 1, "b": {"c": 4}}),
        ('[{"id": 1}, {"id": 2}', [{"id": 1}, {"id": 2}]),
        ('[[1, 2], [3', [[1, 2], [3]]),
    ],
)
def test_unclosed_containers_are_closed(raw, expected):
    result = transform_json(raw)

    assert result.ok
    assert json.loads(result.text) == expected
    assert "completed_truncation" in result.repairs


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # A partial value cannot be trusted, so the pair goes.
        ('{"a": 1, "b": "unterminat', {"a": 1}),
        # A key with no value at all.
        ('{"a": 1, "b":', {"a": 1}),
        # A comma left by the cut.
        ('{"a": 1,', {"a": 1}),
    ],
)
def test_partial_content_is_dropped_not_invented(raw, expected):
    result = transform_json(raw)

    assert result.ok
    assert json.loads(result.text) == expected
    assert "null" not in result.text


def test_a_realistic_truncated_event_payload_recovers_its_complete_fields():
    raw = (
        '{"event": "POS_CLOSE_SHIFT_REQUEST", "eventId": 116, "fields": ['
        '{"wire": "close_amount_cents", "type": "Int"}, {"wire": "auth'
    )

    result = transform_json(raw)

    assert result.ok
    payload = json.loads(result.text)
    assert payload["eventId"] == 116
    # The complete entry survives intact. The entry that was cut becomes an empty
    # object rather than disappearing: its opening brace really was in the input,
    # so completing it is faithful, and the empty slot is a visible signal that
    # something was truncated there. No field name or value is invented.
    assert payload["fields"] == [{"wire": "close_amount_cents", "type": "Int"}, {}]


def test_a_complete_payload_records_no_repair():
    # A false positive here would tell the user their input was broken when it
    # was not, which erodes trust in the whole repair list.
    result = transform_json('{"a": 1, "b": 2}')

    assert result.ok
    assert result.repairs == []


def test_escaped_quotes_inside_a_string_do_not_confuse_the_scanner():
    result = transform_json('{"a": "he said \\"hi\\", ok"')

    assert result.ok
    assert json.loads(result.text) == {"a": 'he said "hi", ok'}


def test_truncation_combines_with_the_other_repairs():
    # Single quotes and a trailing comma and a cut, all at once.
    result = transform_json("{'a': 1, 'b': [2,")

    assert result.ok
    assert json.loads(result.text) == {"a": 1, "b": [2]}
    assert "completed_truncation" in result.repairs


def test_something_that_is_not_json_at_all_still_fails():
    # Completion must not manufacture a document out of prose.
    result = transform_json("the cashier closes the shift")

    assert not result.ok


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Nothing complete anywhere: unwind to an empty container rather than
        # failing, at whatever depth the cut happened.
        ('{"p": "a', {}),
        ('["a', []),
        ("{", {}),
        ("[", []),
        ('{"a": {"b": "x', {"a": {}}),
        ('{"a": [{"b": "x', {"a": [{}]}),
        # A complete pair with no trailing comma must survive: it has nothing to
        # mark it safe, and unwinding would discard it.
        ('{"a": "he said \\"hi\\", ok"', {"a": 'he said "hi", ok'}),
        ('{"p": "C:\\\\Users\\\\nav"', {"p": "C:\\Users\\nav"}),
        ('{"u": "https://x/a//b"', {"u": "https://x/a//b"}),
        ('{"a": 1, "ke', {"a": 1}),
    ],
)
def test_any_depth_of_truncation_completes(raw, expected):
    result = transform_json(raw)

    assert result.ok
    assert json.loads(result.text) == expected


def test_a_bare_top_level_string_gets_its_closing_quote():
    # The only character ever added besides a bracket. It adds no content and
    # loses none.
    result = transform_json('"bare string')

    assert result.ok
    assert json.loads(result.text) == "bare string"


def test_completion_never_invents_a_value():
    for raw in ('{"a": 1, "b":', '{"p": "a', '{"a": [1,'):
        result = transform_json(raw)
        assert result.ok
        assert "null" not in result.text
