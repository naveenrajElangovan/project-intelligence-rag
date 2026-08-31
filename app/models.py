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

    version: int = Field(default=1, ge=1, le=10)
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

    version: int = Field(default=1, ge=1, le=10)
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


class RagResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    answer: str
    confidence: str
    project_id: str = Field(alias="projectId")
    sources: list[SourceReference]
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
