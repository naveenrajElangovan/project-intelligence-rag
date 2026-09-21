import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app import main, retrieval


def test_cache_page_retries_completed_transient_reads_only(monkeypatch):
    index = SimpleNamespace(get=Mock(side_effect=[TimeoutError("read ended"), {"ids": ["a"]}]))
    monkeypatch.setattr(retrieval.time, "sleep", lambda _: None)
    value = retrieval.ChromaAccessRetriever._read_cache_page(
        SimpleNamespace(index=index, retry_attempts=2), offset=0, limit=500
    )
    assert value == {"ids": ["a"]} and index.get.call_count == 2
    index.get = Mock(side_effect=ValueError("invalid filter"))
    with pytest.raises(ValueError):
        retrieval.ChromaAccessRetriever._read_cache_page(
            SimpleNamespace(index=index, retry_attempts=3), offset=0
        )
    assert index.get.call_count == 1


def test_warm_timeout_keeps_one_attempt_instead_of_spawning_overlapping_loads(monkeypatch):
    attempts = 0

    async def slow(settings, embedder):
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(0.08)

    monkeypatch.setattr(main, "warm_authorized_lexical_corpora", slow)
    settings = SimpleNamespace(
        lexical_corpus_warm_timeout_seconds=0.01,
        lexical_corpus_warm_retry_seconds=0.005,
        chroma_host="fake",
        chroma_port=8000,
    )
    application = SimpleNamespace(state=SimpleNamespace(lexical_corpus_ready=False))
    asyncio.run(main._warm_lexical_corpora_until_ready(application, settings, None))
    assert attempts == 1 and application.state.lexical_corpus_ready


def test_larger_cache_pages_preserve_full_inventory_and_report_the_cap():
    from langchain_core.documents import Document

    calls = []

    def page(**parameters):
        calls.append((parameters["offset"], parameters["limit"]))
        ids = [
            str(i)
            for i in range(
                parameters["offset"], min(1207, parameters["offset"] + parameters["limit"])
            )
        ]
        return {"ids": ids, "documents": ["body"] * len(ids), "metadatas": [{} for _ in ids]}

    fake = SimpleNamespace(
        text_field="chunk_text",
        project_id="DEMO",
        access_policy_ids=("project:DEMO",),
        lexical_fallback_max_records=2000,
        _read_cache_page=page,
        _document_from_fields=lambda fields, key, score: Document(page_content=key),
    )
    records, truncated = retrieval.ChromaAccessRetriever._fetch_fallback_corpus(fake, ("CODE",))
    assert len(records) == 1207 and not truncated
    assert calls == [(0, 500), (500, 500), (1000, 500)]
    fake.lexical_fallback_max_records = 700
    calls.clear()
    records, truncated = retrieval.ChromaAccessRetriever._fetch_fallback_corpus(fake, ("CODE",))
    assert len(records) == 700 and truncated
    assert calls == [(0, 500), (500, 200)]
