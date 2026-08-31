import asyncio

from langchain_core.documents import Document

from app.config import Settings
from app.grounding import LocalCitationGroundingVerifier
from app.llm import GroundedAnswer, insufficient_evidence_answer, no_access_answer
from app.reranking import LocalMultilingualReranker


def _verifier(monkeypatch, scores: list[float]) -> LocalCitationGroundingVerifier:
    monkeypatch.setattr(
        "app.grounding.predict_local_scores",
        lambda *args, **kwargs: scores,
    )
    return LocalCitationGroundingVerifier(
        Settings(
            _env_file=None, environment="development", local_models_path="/tmp/model",
            grounding_score_threshold=0.65,
            grounding_cross_language_score_threshold=0.60,
            grounding_table_evidence_score_threshold=0.60,
        )
    )


def test_local_grounding_accepts_cited_supported_claim(monkeypatch) -> None:
    verifier = _verifier(monkeypatch, [0.91])
    verdict = asyncio.run(
        verifier.verify(
            "How many files?",
            [Document(page_content="12 Kotlin source files were inspected.")],
            GroundedAnswer(
                answer="12 Kotlin source files were inspected [SOURCE 1].",
                citations=[1],
            ),
        )
    )
    assert verdict.supported is True
    assert verdict.reason_code == "SUPPORTED"


def test_structured_answer_is_verified_without_punishing_labels(monkeypatch) -> None:
    captured: list[tuple[str, str]] = []

    def scores(*args, **kwargs):
        captured.extend(kwargs["pairs"])
        return [0.91] * len(kwargs["pairs"])

    monkeypatch.setattr("app.grounding.predict_local_scores", scores)
    verifier = LocalCitationGroundingVerifier(
        Settings(
            _env_file=None,
            environment="development",
            local_models_path="/tmp/model",
            grounding_score_threshold=0.65,
        )
    )
    evidence = Document(
        page_content=(
            "The close shift event closes the active shift.\n"
            "| Field | Type | Required | Description |\n"
            "|---|---|---|---|\n"
            "| shiftId | string | yes | Shift identifier |\n"
            "| reason | string | no | Closing reason |\n"
            "The consumer persists the event and the nested child validates it."
        )
    )
    answer = GroundedAnswer(
        answer=(
            "The close shift event closes the active shift [SOURCE 1].\n"
            "### Payload fields for the close shift event\n"
            "| Field | Type | Required | Description | Source |\n"
            "|---|---|---|---|---|\n"
            "| shiftId | string | yes | Shift identifier | [SOURCE 1] |\n"
            "| reason | string | no | Closing reason | [SOURCE 1] |\n"
            "1. The consumer persists the event [SOURCE 1].\n"
            "  - The nested child validates it [SOURCE 1]."
        ),
        citations=[1],
    )

    verdict = asyncio.run(verifier.verify("Describe the event", [evidence], answer))

    assert verdict.supported is True
    assert any("Type: string" in claim for claim, _evidence in captured)
    assert all("Payload fields for" not in claim for claim, _evidence in captured)


def test_cross_language_grounding_uses_calibrated_threshold_only_for_mixed_languages(
    monkeypatch,
) -> None:
    spanish_answer = GroundedAnswer(
        answer="La función gestiona la confirmación de pedidos [SOURCE 1].",
        citations=[1],
    )
    english_evidence = Document(
        page_content="The feature manages order confirmation.",
        metadata={"language": "en"},
    )
    verifier = _verifier(monkeypatch, [0.5])

    cross_language = asyncio.run(
        verifier.verify(
            "Háblame de BOT",
            [english_evidence],
            spanish_answer,
            answer_language="es",
        )
    )
    same_language = asyncio.run(
        verifier.verify(
            "Tell me about BOT",
            [english_evidence],
            GroundedAnswer(
                answer="The feature manages order confirmation [SOURCE 1].",
                citations=[1],
            ),
            answer_language="en",
        )
    )

    assert cross_language.supported is True
    assert same_language.supported is False


def test_cross_language_grounding_still_rejects_low_score_claim(monkeypatch) -> None:
    verifier = _verifier(monkeypatch, [-3.0])
    verdict = asyncio.run(
        verifier.verify(
            "Háblame de BOT",
            [
                Document(
                    page_content="The feature manages order confirmation.",
                    metadata={"language": "en"},
                )
            ],
            GroundedAnswer(
                answer="BOT procesa nóminas de empleados [SOURCE 1].",
                citations=[1],
            ),
            answer_language="es",
        )
    )

    assert verdict.supported is False


def test_local_grounding_rejects_invented_number_before_model_score(monkeypatch) -> None:
    verifier = _verifier(monkeypatch, [])
    verdict = asyncio.run(
        verifier.verify(
            "How many files?",
            [Document(page_content="12 Kotlin source files were inspected.")],
            GroundedAnswer(
                answer="99 Kotlin source files were inspected [SOURCE 1].",
                citations=[1],
            ),
        )
    )
    assert verdict.supported is False
    assert verdict.reason_code == "UNSUPPORTED_CLAIM"


def test_local_grounding_accepts_thousands_separator_formatting(monkeypatch) -> None:
    verifier = _verifier(monkeypatch, [0.91])
    verdict = asyncio.run(
        verifier.verify(
            "How many lines?",
            [Document(page_content="12356 nonblank Kotlin lines were present.")],
            GroundedAnswer(
                answer="12,356 nonblank Kotlin lines were present [SOURCE 1].",
                citations=[1],
            ),
        )
    )
    assert verdict.supported is True


def test_local_grounding_does_not_conflate_decimal_and_integer(monkeypatch) -> None:
    verifier = _verifier(monkeypatch, [])
    verdict = asyncio.run(
        verifier.verify(
            "What version?",
            [Document(page_content="Version 314 is deployed.")],
            GroundedAnswer(
                answer="Version 3.14 is deployed [SOURCE 1].",
                citations=[1],
            ),
        )
    )
    assert verdict.supported is False


def test_local_grounding_rejects_unsubstantiated_negation(monkeypatch) -> None:
    verifier = _verifier(monkeypatch, [])
    verdict = asyncio.run(
        verifier.verify(
            "Were tests found?",
            [Document(page_content="Four feature-path tests were discovered.")],
            GroundedAnswer(
                answer="No tests were discovered [SOURCE 1].",
                citations=[1],
            ),
        )
    )
    assert verdict.supported is False


def test_local_grounding_attaches_only_a_supported_missing_citation(monkeypatch) -> None:
    verifier = _verifier(monkeypatch, [0.91])
    answer = asyncio.run(
        verifier.attach_missing_citations(
            [
                Document(page_content="12 Kotlin source files were inspected."),
                Document(page_content="A separate product has 8 files."),
            ],
            GroundedAnswer(
                answer="12 Kotlin source files were inspected.",
                citations=[],
            ),
        )
    )
    assert answer.answer == "12 Kotlin source files were inspected [SOURCE 1]."
    assert answer.citations == [1]


def test_exact_filename_can_pass_bounded_code_threshold(monkeypatch) -> None:
    monkeypatch.setattr("app.reranking.predict_local_scores", lambda *args, **kwargs: [-2.0])
    verifier = LocalMultilingualReranker(
        "model",
        device="cpu",
        model_path="/tmp/model",
        revision="revision",
        top_n=8,
        score_threshold=0.35,
        exact_code_score_threshold=0.10,
        exact_code_retrieval_score_floor=0.80,
        max_chunks_per_source=2,
    )
    documents = [
        Document(
            page_content="android { namespace = com.fordmx.cluster }",
            metadata={
                "title": "app/build.gradle.kts",
                "source_type": "CODE",
                "source_id": "file",
                "score": 0.85,
            },
        )
    ]
    ranked = asyncio.run(
        verifier.rerank("What is configured in app/build.gradle.kts?", documents)
    )
    assert ranked == documents


def test_entity_overview_can_use_a_scoped_lower_rerank_threshold(monkeypatch) -> None:
    monkeypatch.setattr("app.reranking.predict_local_scores", lambda *args, **kwargs: [-2.0])
    reranker = LocalMultilingualReranker(
        "model",
        device="cpu",
        model_path="/tmp/model",
        revision="revision",
        top_n=8,
        score_threshold=0.35,
        exact_code_score_threshold=0.10,
        exact_code_retrieval_score_floor=0.80,
        max_chunks_per_source=2,
    )
    documents = [
        Document(
            page_content="POS Shift manages store shift workflows.",
            metadata={"title": "POS-Shift-Documentation", "source_id": "pos-shift"},
        )
    ]

    assert asyncio.run(reranker.rerank("Tell me about POS", documents)) == []
    assert (
        asyncio.run(
            reranker.rerank(
                "POS application overview features workflows architecture",
                documents,
                score_threshold=0.10,
            )
        )
        == documents
    )


def test_access_denial_and_insufficient_evidence_are_not_conflated() -> None:
    assert "authorized" in no_access_answer("en")
    assert "authorized" not in insufficient_evidence_answer("en")
    assert "enough evidence" in insufficient_evidence_answer("en")
