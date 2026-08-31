import asyncio

from langchain_core.documents import Document

from app.config import Settings
from app.grounding import LocalCitationGroundingVerifier
from app.llm import GroundedAnswer
from app.table_evidence import normalize_table_dialect
from app.workflow_nodes.answering import _rejection_telemetry

TABLE_EVIDENCE = """`ShiftSummary` members:

| Member | Wire name | Contents |
|---|---|---|
| ticketsCount | `tickets_count` | Int |
| totalCredits | `total_credits` | `amount_cents` |
"""


def _verifier(monkeypatch, scores, **overrides) -> LocalCitationGroundingVerifier:
    monkeypatch.setattr("app.grounding.predict_local_scores", lambda *a, **k: scores)
    values = {
        "local_models_path": "/tmp/model",
        "grounding_score_threshold": 0.65,
        "grounding_cross_language_score_threshold": 0.60,
        "grounding_table_evidence_score_threshold": 0.60,
    }
    values.update(overrides)
    return LocalCitationGroundingVerifier(Settings(_env_file=None, environment="development", **values))


def _captured_pairs(monkeypatch, **overrides):
    seen: list = []

    def capture(*args, **kwargs):
        seen.append(kwargs["pairs"])
        return [0.9] * len(kwargs["pairs"])

    monkeypatch.setattr("app.grounding.predict_local_scores", capture)
    values = {
        "local_models_path": "/tmp/model",
        "grounding_score_threshold": 0.65,
        "grounding_cross_language_score_threshold": 0.60,
        "grounding_table_evidence_score_threshold": 0.60,
    }
    values.update(overrides)
    verifier = LocalCitationGroundingVerifier(Settings(_env_file=None, environment="development", **values))
    return verifier, seen


def test_table_evidence_reaches_the_cross_encoder_as_sentences(monkeypatch) -> None:
    verifier, seen = _captured_pairs(monkeypatch)
    asyncio.run(
        verifier.verify(
            "What does the shift summary carry?",
            [Document(page_content=TABLE_EVIDENCE)],
            GroundedAnswer(
                answer="The shift summary carries a ticket count member [SOURCE 1].",
                citations=[1],
            ),
        )
    )
    scored_evidence = seen[0][0][1]
    assert "ticketsCount — Wire name: `tickets_count`; Contents: Int." in scored_evidence
    assert "|---|" not in scored_evidence


def test_linearization_can_be_switched_off(monkeypatch) -> None:
    verifier, seen = _captured_pairs(monkeypatch, linearize_table_evidence=False)
    asyncio.run(
        verifier.verify(
            "What does the shift summary carry?",
            [Document(page_content=TABLE_EVIDENCE)],
            GroundedAnswer(
                answer="The shift summary carries a ticket count member [SOURCE 1].",
                citations=[1],
            ),
        )
    )
    assert "| ticketsCount | `tickets_count` | Int |" in seen[0][0][1]


def test_score_rejection_records_the_score_and_threshold(monkeypatch) -> None:
    verifier = _verifier(monkeypatch, [0.31])
    verdict = asyncio.run(
        verifier.verify(
            "What does the shift summary carry?",
            [Document(page_content=TABLE_EVIDENCE)],
            GroundedAnswer(
                answer="The shift summary carries a ticket count member [SOURCE 1].",
                citations=[1],
            ),
        )
    )
    assert verdict.supported is False
    assert len(verifier.last_rejections) == 1
    rejection = verifier.last_rejections[0]
    assert rejection.reason == "SCORE_BELOW_THRESHOLD"
    assert rejection.threshold == 0.60
    assert rejection.score is not None and 0 < rejection.score < 0.60
    assert rejection.table_evidence is True


def test_anchor_rejection_is_reported_separately_from_a_low_score(monkeypatch) -> None:
    verifier = _verifier(monkeypatch, [])
    verdict = asyncio.run(
        verifier.verify(
            "How many members?",
            [Document(page_content="The summary has 8 members.")],
            GroundedAnswer(answer="The summary has 9 members [SOURCE 1].", citations=[1]),
        )
    )
    assert verdict.supported is False
    assert [r.reason for r in verifier.last_rejections] == [
        "NUMERIC_OR_IDENTIFIER_ANCHOR_ABSENT"
    ]
    assert verifier.last_rejections[0].score is None


def test_missing_citation_is_reported_separately(monkeypatch) -> None:
    verifier = _verifier(monkeypatch, [])
    asyncio.run(
        verifier.verify(
            "How many members?",
            [Document(page_content="The summary has 8 members.")],
            GroundedAnswer(answer="The summary has some members.", citations=[]),
        )
    )
    assert [r.reason for r in verifier.last_rejections] == ["MISSING_OR_INVALID_CITATION"]


def test_negation_rejection_is_reported_separately(monkeypatch) -> None:
    verifier = _verifier(monkeypatch, [])
    asyncio.run(
        verifier.verify(
            "Does it confirm?",
            [Document(page_content="The BOT emits a success status here.")],
            GroundedAnswer(
                answer="The BOT does not emit a failure value here [SOURCE 1].",
                citations=[1],
            ),
        )
    )
    assert [r.reason for r in verifier.last_rejections] == ["NEGATION_UNSUPPORTED"]


def test_rejections_reset_between_verifications(monkeypatch) -> None:
    verifier = _verifier(monkeypatch, [0.31])
    answer = GroundedAnswer(
        answer="The shift summary carries a ticket count member [SOURCE 1].",
        citations=[1],
    )
    documents = [Document(page_content=TABLE_EVIDENCE)]
    asyncio.run(verifier.verify("q", documents, answer))
    assert verifier.last_rejections
    monkeypatch.setattr("app.grounding.predict_local_scores", lambda *a, **k: [0.95])
    asyncio.run(verifier.verify("q", documents, answer))
    assert verifier.last_rejections == []


def test_attach_then_verify_scores_overlapping_pairs_once(monkeypatch) -> None:
    calls: list[list[tuple[str, str]]] = []

    def score(*args, **kwargs):
        calls.append(kwargs["pairs"])
        return [0.95] * len(kwargs["pairs"])

    monkeypatch.setattr("app.grounding.predict_local_scores", score)
    verifier = LocalCitationGroundingVerifier(
        Settings(
            _env_file=None,
            environment="development",
            local_models_path="/tmp/model",
            grounding_score_threshold=0.65,
        )
    )
    documents = [Document(page_content="The project supports shift closure.")]
    answer = GroundedAnswer(
        answer="The project supports shift closure [SOURCE 1].",
        citations=[1],
    )

    attached = asyncio.run(verifier.attach_missing_citations(documents, answer))
    verdict = asyncio.run(verifier.verify("q", documents, attached))

    assert verdict.supported is True
    assert len(calls) == 1


def test_table_threshold_is_opt_in_and_lowers_only_table_evidence(monkeypatch) -> None:
    strict = _verifier(monkeypatch, [0.25])
    answer = GroundedAnswer(
        answer="The shift summary carries a ticket count member [SOURCE 1].",
        citations=[1],
    )
    documents = [Document(page_content=TABLE_EVIDENCE)]
    assert asyncio.run(strict.verify("q", documents, answer)).supported is False

    lenient = _verifier(
        monkeypatch, [0.25], grounding_table_evidence_score_threshold=0.55
    )
    assert asyncio.run(lenient.verify("q", documents, answer)).supported is True

    prose = [Document(page_content="The shift summary carries a ticket count member.")]
    assert asyncio.run(lenient.verify("q", prose, answer)).supported is False


def test_cross_language_threshold_still_wins_over_the_table_threshold(monkeypatch) -> None:
    verifier = _verifier(
        monkeypatch,
        [0.5],
        grounding_table_evidence_score_threshold=0.55,
        grounding_cross_language_score_threshold=0.60,
    )
    verdict = asyncio.run(
        verifier.verify(
            "q",
            [Document(page_content=TABLE_EVIDENCE, metadata={"language": "en"})],
            GroundedAnswer(
                answer="El resumen de turno lleva un miembro de conteo [SOURCE 1].",
                citations=[1],
            ),
            answer_language="es",
        )
    )
    assert verdict.supported is True


def test_rejection_telemetry_is_flat_and_content_free(monkeypatch) -> None:
    verifier = _verifier(monkeypatch, [0.31])
    asyncio.run(
        verifier.verify(
            "q",
            [Document(page_content=TABLE_EVIDENCE)],
            GroundedAnswer(
                answer="The shift summary carries a ticket count member [SOURCE 1].",
                citations=[1],
            ),
        )
    )
    summary = _rejection_telemetry(verifier.last_rejections)
    assert summary["grounding_rejected_claim_count"] == 1
    assert summary["grounding_rejection_reasons"] == "SCORE_BELOW_THRESHOLD=1"
    assert summary["grounding_rejected_table_evidence_count"] == 1
    assert summary["grounding_applied_threshold"] == 0.60
    assert all(isinstance(value, (int, float, str)) for value in summary.values())


def test_page_and_document_tables_have_identical_grounding_rejection_telemetry(
    monkeypatch,
) -> None:
    page = normalize_table_dialect(
        "Member | Wire name | Contents\n"
        "ticketsCount | `tickets_count` | Int\n"
        "totalCredits | `total_credits` | `amount_cents`"
    )
    document = (
        "| Member | Wire name | Contents |\n"
        "| --- | --- | --- |\n"
        "| ticketsCount | `tickets_count` | Int |\n"
        "| totalCredits | `total_credits` | `amount_cents` |"
    )
    answer = GroundedAnswer(
        answer="The shift summary carries a ticket count member [SOURCE 1].",
        citations=[1],
    )
    summaries = []
    for evidence in (page, document):
        verifier = _verifier(monkeypatch, [0.31])
        asyncio.run(verifier.verify("q", [Document(page_content=evidence)], answer))
        summaries.append(_rejection_telemetry(verifier.last_rejections))

    assert summaries[0] == summaries[1]
    assert summaries[0]["grounding_rejected_table_evidence_count"] == 1


def test_rejection_telemetry_is_empty_when_nothing_was_rejected() -> None:
    assert _rejection_telemetry([]) == {}
