"""Overlapped translation preserves the serial retrieval result exactly."""

import asyncio
import json

from langchain_core.documents import Document

from app.config import Settings
from app.llm import TokenUsage
from app.models import RagRequest
from app.retrieval_pipeline import BM25Retriever, ReciprocalRankFusion
from app.vocabulary import CorpusVocabulary
from app.workflow_nodes.retrieval import RetrievalNodesMixin


ORIGINAL = "What is the POS price check flow?"
TRANSLATED = "¿Cuál es el flujo de consulta de precios POS?"


def _document(chunk_id: str, score: float) -> Document:
    return Document(
        page_content=f"Price check evidence {chunk_id}.",
        metadata={
            "chunk_id": chunk_id,
            "project_id": "DEMO",
            "access_policy_ids": ["project:DEMO"],
            "source_type": "PAGE",
            "reference": chunk_id,
            "score": score,
        },
    )


class FixedRetriever:
    def __init__(self, base_started: asyncio.Event) -> None:
        self.base_started = base_started
        self.queries: list[str] = []

    async def ainvoke_scoped(self, query: str, _source_types):
        self.queries.append(query)
        if query == ORIGINAL:
            self.base_started.set()
            await asyncio.sleep(0.01)
            return [_document("shared", 0.99), _document("english", 0.95)]
        return [_document("shared", 0.91), _document("spanish", 0.90)]

    def drain_usage(self):
        return {"embedding_tokens": 0, "read_units": 0, "retry_count": 0}


class ConcurrentTranslator:
    base_started: asyncio.Event
    value = TRANSLATED

    def __init__(self, *_args) -> None:
        self.last_usage = TokenUsage()

    async def translate_to_spanish(self, _question: str) -> str:
        await asyncio.wait_for(self.base_started.wait(), timeout=0.5)
        return self.value


class RetrievalHarness(RetrievalNodesMixin):
    def __init__(self, retriever: FixedRetriever) -> None:
        self._settings = Settings(
            _env_file=None,
            environment="development",
            max_query_variants=2,
            prefilter_min_dense_score=0.0,
        )
        self._request = RagRequest(
            projectId="DEMO",
            collectionName=self._settings.chroma_collection,
            question=ORIGINAL,
            accessPolicyIds=["project:DEMO"],
        )
        self._retriever = retriever
        self._vocabulary = CorpusVocabulary(entities=("pos",))
        self._sparse_retriever = BM25Retriever()
        self._candidate_fusion = ReciprocalRankFusion()
        self._query_planner_factory = ConcurrentTranslator


def _snapshot(result: dict) -> bytes:
    protected = (
        "retrieval_rrf_score",
        "query_candidate_ranks",
        "primary_query_rank",
        "score",
    )
    value = [
        (
            str(document.metadata["chunk_id"]),
            {key: document.metadata.get(key) for key in protected},
        )
        for document in result["candidates"]
    ]
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


async def _serial_and_overlapped():
    serial_event = asyncio.Event()
    serial_event.set()
    serial_retriever = FixedRetriever(serial_event)
    serial = await RetrievalHarness(serial_retriever)._retrieve(
        {
            "queries": (ORIGINAL, TRANSLATED),
            "resolved_question": ORIGINAL,
            "rerank_queries": (ORIGINAL, TRANSLATED),
        }
    )

    overlap_event = asyncio.Event()
    ConcurrentTranslator.base_started = overlap_event
    overlap_retriever = FixedRetriever(overlap_event)
    overlapped = await RetrievalHarness(overlap_retriever)._retrieve(
        {
            "queries": (ORIGINAL, ""),
            "resolved_question": ORIGINAL,
            "rerank_queries": (ORIGINAL,),
            "translation_slot": 1,
        }
    )
    return serial, serial_retriever, overlapped, overlap_retriever


def test_overlapped_and_serial_retrieval_are_byte_identical() -> None:
    serial, _serial_retriever, overlapped, overlap_retriever = asyncio.run(
        _serial_and_overlapped()
    )

    assert _snapshot(overlapped) == _snapshot(serial)
    assert overlapped["queries"] == (ORIGINAL, TRANSLATED)
    assert overlap_retriever.queries == [ORIGINAL, TRANSLATED]


def test_translation_is_issued_even_when_first_pass_is_strong() -> None:
    _serial, _serial_retriever, _overlapped, overlap_retriever = asyncio.run(
        _serial_and_overlapped()
    )

    assert TRANSLATED in overlap_retriever.queries


def test_unsafe_translation_never_reaches_retrieval() -> None:
    async def scenario():
        event = asyncio.Event()
        ConcurrentTranslator.base_started = event
        ConcurrentTranslator.value = "astronomy and lunar geology"
        retriever = FixedRetriever(event)
        try:
            result = await RetrievalHarness(retriever)._retrieve(
                {
                    "queries": (ORIGINAL, ""),
                    "resolved_question": ORIGINAL,
                    "rerank_queries": (ORIGINAL,),
                    "translation_slot": 1,
                }
            )
        finally:
            ConcurrentTranslator.value = TRANSLATED
        return result, retriever

    result, retriever = asyncio.run(scenario())

    assert retriever.queries == [ORIGINAL]
    assert result["queries"] == (ORIGINAL,)
