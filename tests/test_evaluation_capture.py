from types import SimpleNamespace

from app.quality_tracing import capture_evaluation_evidence, record_candidate_scores
from app.quality_tracing import record_evaluation_rejections


def test_rejected_answer_diagnostics_are_private_bounded_and_redacted():
    with capture_evaluation_evidence(False) as disabled:
        record_evaluation_rejections(["Authorization: Bearer private-value"])
        assert disabled is None
    with capture_evaluation_evidence(True) as evidence:
        record_evaluation_rejections(["Authorization: Bearer private-value"] * 65)
    assert len(evidence["rejected_answer_claims"]) == 64
    assert "private-value" not in str(evidence)
    assert evidence["overflow"] is True


def doc(value="issue-1"):
    return SimpleNamespace(
        page_content="private body",
        metadata={
            "source_id": value,
            "project_id": "OPS",
            "locator": "current:1",
            "access_policy_id": "project:OPS",
            "unrelated_private_field": "secret",
        },
    )


def test_capture_is_request_scoped_and_contains_only_evidence_identity():
    with capture_evaluation_evidence(True) as outer:
        record_candidate_scores([doc()])
        with capture_evaluation_evidence(False) as disabled:
            assert disabled is None
            record_candidate_scores([doc("hidden")])
        with capture_evaluation_evidence(True) as nested:
            record_candidate_scores([doc("other")])
        assert nested["candidates"][0]["source_id"] == "other"
        assert len(outer["candidates"]) == 1
        assert "private" not in str(outer) and "secret" not in str(outer)
    record_candidate_scores([doc("outside")])
    assert len(outer["candidates"]) == 1


def test_capture_limit_is_explicit_instead_of_silent():
    with capture_evaluation_evidence(True) as evidence:
        record_candidate_scores([doc()] * 2001)
    assert len(evidence["candidates"]) == 2000
    assert evidence["overflow"] is True
