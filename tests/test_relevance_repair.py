import asyncio
from types import SimpleNamespace

from langchain_core.documents import Document

from app.config import Settings
from app.llm import GroundedAnswer, GroundingVerdict, TokenUsage
from app.models import RagRequest
from app.workflow_nodes.answering import (
    AnswerNodesMixin,
    _deterministic_single_record_table,
)


INITIAL = (
    "The evidence describes a neighboring process [SOURCE 1]. "
    "It also documents an unrelated control [SOURCE 1]. "
    "Those statements do not identify the requested record [SOURCE 1]."
)
REPAIRED = (
    "Record `entry-17` is the selected record [SOURCE 1]. "
    "Its category is `audit` [SOURCE 1]. "
    "Its state is `accepted` [SOURCE 1]."
)


class _Generator:
    def __init__(self) -> None:
        self.last_usage = TokenUsage()
        self.model_name = "test-generator"
        self.repairs = 0
        self.questions: list[str] = []
        self.styles: list[str] = []
        self.repair_focuses: list[str] = []

    async def repair(self, question, documents, language, invalid, **kwargs):
        self.repairs += 1
        self.questions.append(question)
        self.styles.append(kwargs.get("answer_style", ""))
        self.repair_focuses.append(kwargs.get("repair_focus", ""))
        return GroundedAnswer(answer=REPAIRED, citations=[1])


class _Verifier:
    def __init__(self, *, repaired_is_relevant=True, repaired_is_supported=True):
        self.last_usage = TokenUsage()
        self.model_name = "test-verifier"
        self.last_rejections = []
        self.last_accepted_scores = []
        self.repaired_is_relevant = repaired_is_relevant
        self.repaired_is_supported = repaired_is_supported
        self.relevance_calls = 0
        self.relevance_questions: list[str] = []
        self.verified_questions: list[str] = []

    async def verify(self, question, documents, answer, **kwargs):
        self.verified_questions.append(question)
        supported = answer.answer != REPAIRED or self.repaired_is_supported
        return GroundingVerdict(
            supported=supported,
            unsupported_claims=[] if supported else [REPAIRED],
            reason_code="SUPPORTED" if supported else "UNSUPPORTED_CLAIM",
        )

    async def attach_missing_citations(self, documents, answer):
        return answer

    async def answer_addresses_question(self, question, answer, *, threshold):
        self.relevance_calls += 1
        self.relevance_questions.append(question)
        if self.relevance_calls == 1:
            return False, 0.01
        return self.repaired_is_relevant, 0.9 if self.repaired_is_relevant else 0.02


class _ShapeGenerator(_Generator):
    def __init__(self) -> None:
        super().__init__()
        self.answer_styles: list[str] = []

    async def answer(self, question, documents, language, *, answer_style="concise"):
        self.answer_styles.append(answer_style)
        return GroundedAnswer(
            answer="Record `entry-17` has details in the table below [SOURCE 1].",
            citations=[1],
        )

    async def repair(self, question, documents, language, invalid, **kwargs):
        self.repairs += 1
        self.styles.append(kwargs.get("answer_style", ""))
        return GroundedAnswer(
            answer=("Record `entry-17` has category `audit` and state `accepted` [SOURCE 1]."),
            citations=[1],
        )


def _document() -> Document:
    return Document(
        page_content="entry-17 category audit state accepted",
        metadata={
            "chunk_id": "c1",
            "source_id": "s1",
            "source_type": "PAGE",
            "title": "Record contract",
            "reference": "DOC-1",
        },
    )


def _verify(*, repaired_is_relevant=True, repaired_is_supported=True):
    workflow = AnswerNodesMixin()
    workflow._request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="Give me one full record detail",
        accessPolicyIds=["project:DEMO"],
    )
    workflow._settings = Settings(_env_file=None, environment="development")
    workflow._vocabulary = SimpleNamespace(entities=(), code_extensions=())
    workflow._generator = _Generator()
    workflow._grounding_verifier = _Verifier(
        repaired_is_relevant=repaired_is_relevant,
        repaired_is_supported=repaired_is_supported,
    )
    canonical = "Provide one audit entry record with its details supported by the evidence."
    state = {
        "documents": [_document()],
        "generated": GroundedAnswer(answer=INITIAL, citations=[1]),
        "resolved_question": canonical,
        "answer_relevance_query": "audit entry record details",
        "language": "en",
        "query_intent": "CODE_ASSISTED",
        "source_route": "MIXED",
        "answer_style": "single_record_details",
    }
    result = asyncio.run(workflow._verify_grounding(state))
    return result, workflow, canonical


def test_supported_but_irrelevant_answer_gets_one_bounded_repair() -> None:
    result, workflow, canonical = _verify()

    assert result["grounded"] is True
    assert result["grounding_reason"] == "RELEVANCE_REPAIRED_SUPPORTED"
    assert result["generated"].answer == REPAIRED
    assert workflow._generator.repairs == 1
    assert workflow._generator.questions == [canonical]
    assert workflow._generator.styles == ["single_record_details"]
    assert workflow._generator.repair_focuses == ["answer_relevance"]
    assert workflow._grounding_verifier.verified_questions == [canonical, canonical]
    assert workflow._grounding_verifier.relevance_questions == [
        "audit entry record details",
        "audit entry record details",
    ]


def test_relevance_repair_and_extractive_recovery_fail_closed_when_both_are_irrelevant() -> None:
    result, workflow, _ = _verify(repaired_is_relevant=False)

    assert result["grounded"] is False
    assert result["grounding_reason"] == "ANSWER_NOT_RELEVANT"
    assert workflow._generator.repairs == 1
    assert workflow._grounding_verifier.relevance_calls == 3


def test_unsupported_repair_can_recover_only_from_independently_grounded_source_text() -> None:
    result, workflow, _ = _verify(repaired_is_supported=False)

    assert result["grounded"] is True
    assert result["grounding_reason"] == "EXTRACTIVE_EVIDENCE_SUPPORTED"
    assert "entry-17 category audit state accepted" in result["generated"].answer
    assert workflow._generator.repairs == 1
    assert workflow._grounding_verifier.relevance_calls == 2


def test_grounded_neighboring_subject_is_rejected_after_zero_relevance_context() -> None:
    workflow = AnswerNodesMixin()
    workflow._request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="What is memoy here?",
        accessPolicyIds=["project:DEMO"],
    )
    workflow._settings = Settings(_env_file=None, environment="development")
    workflow._vocabulary = SimpleNamespace(entities=(), code_extensions=())
    workflow._generator = _Generator()
    workflow._grounding_verifier = _Verifier()
    result = asyncio.run(
        workflow._verify_grounding(
            {
                "documents": [_document()],
                "generated": GroundedAnswer(answer=INITIAL, citations=[1]),
                "resolved_question": "What is memoy here?",
                "answer_relevance_query": "What is memoy here?",
                "context_failure_reason": "LOW_RELEVANCE",
                "language": "en",
                "query_intent": "CODE_ASSISTED",
                "source_route": "MIXED",
                "answer_style": "concise",
            }
        )
    )

    assert result["grounded"] is False
    assert result["grounding_reason"] == "EVIDENCE_NOT_TOPICAL"


def test_single_record_generation_enforces_a_real_details_table() -> None:
    workflow = AnswerNodesMixin()
    workflow._request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="Give me one full audit entry details",
        accessPolicyIds=["project:DEMO"],
    )
    workflow._settings = Settings(_env_file=None, environment="development")
    workflow._vocabulary = SimpleNamespace(entities=(), code_extensions=())
    workflow._generator = _ShapeGenerator()
    workflow._grounding_verifier = _Verifier()
    workflow._retriever = SimpleNamespace()
    result = asyncio.run(
        workflow._generate(
            {
                "documents": [_document()],
                "resolved_question": (
                    "Provide one audit entry record with its details supported by the evidence."
                ),
                "language": "en",
                "query_intent": "CODE_ASSISTED",
                "source_route": "MIXED",
                "reconstruct_parent_records": True,
            }
        )
    )

    assert workflow._generator.answer_styles == ["single_record_details"]
    assert workflow._generator.styles == []
    assert workflow._generator.repairs == 0
    assert result["generated"].answer.startswith("| Attribute | Value | Source |")


def test_locator_matched_table_row_is_extracted_without_sibling_records() -> None:
    document = Document(
        page_content=(
            "| Name | Identifier | Version | Meaning |\n"
            "|---|---|---|---|\n"
            "| selected-entry | 17 | 2 | requested record |\n"
            "| neighboring-entry | 18 | 1 | different record |"
        ),
        metadata={"locator": "selected-entry"},
    )

    generated = _deterministic_single_record_table([document], "en")

    assert generated is not None
    assert "selected-entry" in generated.answer
    assert "requested record" in generated.answer
    assert "neighboring-entry" not in generated.answer
    assert generated.citations == [1]


def test_locator_bounded_prose_record_is_rendered_without_model_synthesis() -> None:
    document = Document(
        page_content=(
            "### entry-17 — id 17, version 2\n"
            "Payload type AuditEntry. Fields are category (audit) and state (accepted)."
        ),
        metadata={"locator": "entry-17"},
    )

    generated = _deterministic_single_record_table([document], "en")

    assert generated is not None
    assert "| Record | entry-17 — id 17, version 2 | [SOURCE 1] |" in generated.answer
    assert "Payload type AuditEntry" in generated.answer
    assert generated.citations == [1]


def test_prose_extractor_rejects_multiple_record_boundaries() -> None:
    document = Document(
        page_content=(
            "### entry-17\nThis record has enough material details to otherwise qualify.\n"
            "### entry-18\nThis neighboring record must never be mixed into the answer."
        ),
        metadata={"locator": "entry-17"},
    )

    assert _deterministic_single_record_table([document], "en") is None
