from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import get_settings



# Prose questions stay small: they are interpolated into every prompt, stored as
# conversation history, and rewritten by the planner. A pasted JSON document is
# none of those things -- it is converted deterministically before the graph runs
# and never reaches a model -- so it gets its own, much larger ceiling.
MAX_PROSE_QUESTION_CHARACTERS = 4_000
MAX_PAYLOAD_QUESTION_CHARACTERS = 1_000_000


def looks_like_payload(question: str) -> bool:
    """Cheap structural test: does this message consist mostly of one JSON document?

    Deliberately not the real parser. app.workflow_support.json_transform does the
    authoritative decode, repair, and error reporting; this only decides whether a
    long message is allowed through the contract at all. It must stay dependency
    free, because json_transform imports this module.
    """

    stripped = question.strip()
    if len(stripped) <= MAX_PROSE_QUESTION_CHARACTERS:
        return True
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped[4:].strip() if stripped[:4].lower() == "json" else stripped.strip()
    opener = stripped[:1]
    closer = stripped[-1:]
    if (opener, closer) in {("{", "}"), ("[", "]")}:
        return True
    # An escaped document arrives as one long quoted string.
    return opener == '"' and closer == '"' and ("{" in stripped or "[" in stripped)


class ConversationMessage(BaseModel):
    """Bounded prior chat text used only to resolve follow-up references."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ConversationEntity(BaseModel):
    """One bounded, user-visible subject carried across conversation turns."""

    type: str = Field(default="subject", min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=500)
    canonical_value: str = Field(alias="canonicalValue", min_length=1, max_length=500)


class ConversationContext(BaseModel):
    """Server-owned semantic state; it helps retrieval but is never evidence."""

    model_config = ConfigDict(populate_by_name=True)

    version: int = Field(default=2, ge=1, le=10)
    summary: str = Field(default="", max_length=2000)
    active_subject: str = Field(default="", alias="activeSubject", max_length=500)
    entities: list[ConversationEntity] = Field(default_factory=list, max_length=12)
    last_intent: str = Field(default="", alias="lastIntent", max_length=80)
    last_resolved_question: str = Field(
        default="", alias="lastResolvedQuestion", max_length=4000
    )
    state_revision: int = Field(default=0, alias="stateRevision", ge=0)


class ConversationContextUpdate(BaseModel):
    """Semantic state derived during planning and returned to the owning backend."""

    model_config = ConfigDict(populate_by_name=True)

    version: int = Field(default=2, ge=1, le=10)
    standalone_question: str = Field(alias="standaloneQuestion", min_length=2, max_length=4000)
    active_subject: str = Field(default="", alias="activeSubject", max_length=500)
    entities: list[ConversationEntity] = Field(default_factory=list, max_length=12)
    intent: str = Field(default="", max_length=80)
    resolution_confidence: float = Field(
        default=1.0, alias="resolutionConfidence", ge=0.0, le=1.0
    )


class RagRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(alias="projectId", min_length=1, max_length=100)
    collection_name: str = Field(
        alias="collectionName", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,62}$"
    )
    text_field: str = Field(
        default="chunk_text",
        alias="textField",
        pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$",
    )
    embedding_field: str = Field(
        default="embedding_text",
        alias="embeddingField",
        pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$",
    )
    embedding_model: str = Field(
        default_factory=lambda: get_settings().supported_embedding_models[0],
        alias="embeddingModel",
        pattern=r"^[A-Za-z0-9_.-]{1,100}$",
    )
    schema_version: str = Field(
        default_factory=lambda: get_settings().supported_schema_versions[0],
        alias="schemaVersion",
        pattern=r"^[A-Za-z0-9_.-]{1,40}$",
    )
    question: str = Field(min_length=2, max_length=MAX_PAYLOAD_QUESTION_CHARACTERS)
    access_policy_ids: list[str] = Field(alias="accessPolicyIds", min_length=1, max_length=100)
    model_profile: Literal["budget", "standard", "complex"] = Field(
        default="standard", alias="modelProfile"
    )
    conversation_history: list[ConversationMessage] = Field(
        default_factory=list, alias="conversationHistory", max_length=12
    )
    conversation_context: ConversationContext = Field(
        default_factory=ConversationContext, alias="conversationContext"
    )

    @model_validator(mode="after")
    def bound_prose_questions(self) -> "RagRequest":
        """Allow a large question only when it is a payload, never as prose."""

        if not looks_like_payload(self.question):
            raise ValueError(
                "question may exceed "
                f"{MAX_PROSE_QUESTION_CHARACTERS} characters only when it is a "
                "single JSON document"
            )
        return self


class SourceReference(BaseModel):
    type: str
    title: str
    reference: str
    url: str | None = None
    locator: str | None = None
    language: str | None = None


class ArtifactReference(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str
    release_id: str = Field(alias="releaseId")
    file_name: str = Field(alias="fileName")
    format: str
    item_count: int = Field(alias="itemCount", ge=0)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    url: str


class AnswerStatus(StrEnum):
    """The only externally observable outcomes of a factual request."""

    ANSWERED = "ANSWERED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    ACCESS_DENIED = "ACCESS_DENIED"


class Coverage(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ResolvedEntity(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str = Field(default="subject", min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=500)
    canonical_id: str = Field(alias="canonicalId", min_length=1, max_length=500)


class CompletenessRequirements(BaseModel):
    all_items: bool = Field(default=False, alias="all")
    all_fields: bool = Field(default=False, alias="allFields")
    latest: bool = False
    compare: bool = False


class ResolvedRequest(BaseModel):
    """Standalone, policy-bounded request produced before retrieval."""

    model_config = ConfigDict(populate_by_name=True)

    standalone_request: str = Field(alias="standaloneRequest", min_length=2, max_length=4000)
    intent: str = Field(min_length=1, max_length=80)
    operation: str = Field(default="ANSWER", min_length=1, max_length=80)
    referenced_entities: list[ResolvedEntity] = Field(
        default_factory=list, alias="referencedEntities", max_length=20
    )
    allowed_source_categories: list[str] = Field(
        default_factory=list, alias="allowedSourceCategories", max_length=50
    )
    expected_answer_shape: str = Field(
        default="NARRATIVE", alias="expectedAnswerShape", max_length=40
    )
    completeness: CompletenessRequirements = Field(
        default_factory=CompletenessRequirements
    )


class RagResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    answer: str
    status: AnswerStatus = AnswerStatus.INSUFFICIENT_EVIDENCE
    confidence: str
    project_id: str = Field(alias="projectId")
    sources: list[SourceReference]
    citations: list[SourceReference] = Field(default_factory=list)
    artifacts: list[ArtifactReference] = Field(default_factory=list)
    resolved_intent: str = Field(default="", alias="resolvedIntent")
    resolved_entities: list[ResolvedEntity] = Field(
        default_factory=list, alias="resolvedEntities"
    )
    coverage: Coverage = Coverage.NOT_APPLICABLE
    failure_reason: str | None = Field(default=None, alias="failureReason")
    missing_information: list[str] = Field(alias="missingInformation")
    evidence_status: str = Field(default="UNKNOWN", alias="evidenceStatus")
    context_quality: str = Field(default="UNKNOWN", alias="contextQuality")
    context_relevance: float = Field(default=0.0, alias="contextRelevance", ge=0.0, le=1.0)
    context_completeness: float = Field(default=0.0, alias="contextCompleteness", ge=0.0, le=1.0)
    degradation: list[str] = Field(default_factory=list)
    refusal_reason: str | None = Field(default=None, alias="refusalReason")
    conversation_context_update: ConversationContextUpdate | None = Field(
        default=None, alias="conversationContextUpdate"
    )

    @model_validator(mode="after")
    def keep_legacy_sources_and_citations_compatible(self) -> "RagResponse":
        """Expose the new citations field while preserving existing clients."""

        if self.status == AnswerStatus.ANSWERED and self.sources and not self.citations:
            self.citations = list(self.sources)
        elif self.citations and not self.sources:
            self.sources = list(self.citations)
        return self
