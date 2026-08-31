"""A pasted document could never reach the converter: the request contract capped
every question at 4000 characters, so a big JSON body was rejected with a 422
before any of the conversion code ran."""

import json

import pytest
from pydantic import ValidationError

from app.models import (
    MAX_PAYLOAD_QUESTION_CHARACTERS,
    MAX_PROSE_QUESTION_CHARACTERS,
    RagRequest,
    looks_like_payload,
)


def _request(question: str) -> RagRequest:
    return RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question=question,
        accessPolicyIds=["project:DEMO"],
    )


def _big_object(entries: int = 4000) -> str:
    return json.dumps({f"key_{index}": index for index in range(entries)})


def test_a_large_json_object_is_accepted():
    payload = _big_object()
    assert len(payload) > MAX_PROSE_QUESTION_CHARACTERS
    assert _request(payload).question == payload


def test_a_large_json_array_is_accepted():
    payload = json.dumps([{"index": index} for index in range(2000)])
    assert len(payload) > MAX_PROSE_QUESTION_CHARACTERS
    assert _request(payload).question == payload


def test_a_large_fenced_payload_is_accepted():
    assert _request(f"```json\n{_big_object()}\n```") is not None


def test_a_large_escaped_document_string_is_accepted():
    payload = json.dumps(_big_object())
    assert _request(payload) is not None


def test_long_prose_is_still_rejected():
    with pytest.raises(ValidationError, match="single JSON document"):
        _request("why " * 2000)


def test_prose_wrapped_around_a_big_payload_is_rejected():
    # Otherwise the payload ceiling becomes the prose ceiling: append a brace to
    # any essay and it would be admitted.
    with pytest.raises(ValidationError):
        _request("please explain all of this to me " * 200 + _big_object())


def test_short_prose_is_unaffected():
    assert _request("what does the bot application do?") is not None


def test_the_hard_ceiling_still_applies_to_a_payload():
    with pytest.raises(ValidationError):
        _request("[" + "1," * MAX_PAYLOAD_QUESTION_CHARACTERS + "1]")


def test_short_text_is_never_judged_by_shape():
    # Below the prose ceiling the shape test must not run at all, or ordinary
    # questions would start being classified as payloads.
    assert looks_like_payload("is this valid?") is True
