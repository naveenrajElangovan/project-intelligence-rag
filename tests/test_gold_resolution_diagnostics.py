"""The preflight must say why a gold case failed, not only that it did."""

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "run_retrieval_eval",
    Path(__file__).resolve().parents[1] / "evaluation" / "run_retrieval_eval.py",
)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def _manifest() -> dict[str, dict[str, str]]:
    return {
        "chunk-1": {
            "structure_path": '["POS_START_SHIFT"]',
            "title": "Event Contract",
            "source_id": "page:1",
            "doc_category": "narrative",
            "entity_key": "POS_START_SHIFT_EVENT",
        },
        "chunk-2": {
            "structure_path": '["Registry"]',
            "title": "Event Contract",
            "source_id": "page:1",
            "doc_category": "narrative",
            "entity_key": "LOGIN_POS_EVENT",
        },
    }


def _case(case_id: str, field: str, value: str) -> dict[str, object]:
    return {
        "id": case_id,
        "answerable": True,
        "project_id": "T2.0",
        "gold_match": {"any_of": [{"field": field, "contains": value}]},
    }


def test_entity_key_is_part_of_the_manifest_contract() -> None:
    """A registry entry names its event here even when it is not a heading."""

    assert "entity_key" in _MODULE._MANIFEST_FIELDS


def test_the_manifest_version_moves_with_the_field_list() -> None:
    """A cached manifest from the old schema must be rejected, not reused."""

    assert _MODULE._MANIFEST_VERSION >= 4


def test_a_predicate_addressed_to_the_wrong_field_is_reported_repointable() -> None:
    case = _case("registry-login", "structure_path", "LOGIN_POS_EVENT")
    report = _MODULE._unresolved_diagnostics([case], _manifest())

    assert report["repointable_cases"] == 1
    assert report["absent_from_corpus_cases"] == 0
    entry = report["by_case"]["registry-login"]
    assert entry["verdict"] == "REPOINTABLE"
    assert entry["present_in_other_fields"]["LOGIN_POS_EVENT"] == ["entity_key"]


def test_a_value_the_corpus_does_not_carry_is_reported_absent() -> None:
    case = _case("section-botguide-001", "structure_path", "[BOTGUIDE-001]")
    report = _MODULE._unresolved_diagnostics([case], _manifest())

    assert report["absent_from_corpus_cases"] == 1
    assert report["by_case"]["section-botguide-001"]["verdict"] == "ABSENT_FROM_CORPUS"


def test_the_two_causes_are_counted_separately_in_the_failure() -> None:
    cases = [
        _case("repointable", "structure_path", "LOGIN_POS_EVENT"),
        _case("absent", "structure_path", "[BOTGUIDE-001]"),
    ]
    with pytest.raises(ValueError) as failure:
        _MODULE._validate_gold_resolution(cases, _manifest(), minimum_rate=0.95)

    message = str(failure.value)
    assert "1 unresolved predicates name a value the corpus carries" in message
    assert "1 name a value absent from the corpus entirely" in message


def test_a_resolvable_entity_key_predicate_passes_the_preflight() -> None:
    case = _case("registry-login", "entity_key", "LOGIN_POS_EVENT")
    report = _MODULE._validate_gold_resolution(case and [case], _manifest())

    assert report["gold_resolution_rate"] == 1.0


def test_a_retired_case_is_excluded_from_scoring_and_reported() -> None:
    """Withdrawn, not deleted: the reason has to survive in the report."""

    cases = [
        _case("live", "entity_key", "LOGIN_POS_EVENT"),
        {
            **_case("gone", "structure_path", "[PLAT-001]"),
            "retired": True,
            "retired_reason": "Absent from the corpus and from the source repositories.",
        },
    ]
    report = _MODULE._validate_gold_resolution(cases, _manifest())

    assert report["answerable_cases"] == 1
    assert report["gold_resolution_rate"] == 1.0
    assert report["retired_cases"] == 1
    assert "gone" in report["retired_case_reasons"]


def test_a_retirement_without_a_reason_is_refused(tmp_path) -> None:
    import json

    suite = tmp_path / "suite.jsonl"
    suite.write_text(
        json.dumps({"id": "gone", "answerable": True, "retired": True}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="retired_reason"):
        _MODULE._load_evaluation_cases(suite)
