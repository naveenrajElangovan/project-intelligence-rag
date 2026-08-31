"""The query embedder is on the hot path and is called from several threads."""

import threading

from app.embedding import LocalMultilingualEmbedder


class _CountingEmbedder(LocalMultilingualEmbedder):
    """Counts forward passes instead of loading a model."""

    def __init__(self, **kwargs) -> None:
        super().__init__("stub", device="cpu", dimensions=4, **kwargs)
        self.encode_calls = 0
        self.encoded_texts: list[str] = []

    def _encode(self, texts: list[str]) -> None:
        self.encode_calls += 1
        self.encoded_texts.extend(texts)
        with self._cache_lock:
            for offset, text in enumerate(texts):
                self._cache[text] = [float(offset), 0.0, 0.0, 1.0]


def test_repeated_query_is_embedded_once() -> None:
    """A completeness repair re-retrieves the same query; it must not re-embed."""

    embedder = _CountingEmbedder()
    first = embedder.embed_query("how does close shift work")
    second = embedder.embed_query("how does close shift work")
    assert first == second
    assert embedder.encode_calls == 1


def test_duplicate_queries_in_one_batch_are_embedded_once() -> None:
    embedder = _CountingEmbedder()
    embedder.embed_queries(["alpha", "beta", "alpha"])
    assert embedder.encoded_texts == ["alpha", "beta"]
    assert embedder.encode_calls == 1


def test_queries_are_returned_in_request_order() -> None:
    embedder = _CountingEmbedder()
    vectors = embedder.embed_queries(["alpha", "beta", "alpha"])
    assert vectors[0] == vectors[2]
    assert vectors[0] != vectors[1]


def test_whitespace_only_difference_hits_the_cache() -> None:
    embedder = _CountingEmbedder()
    embedder.embed_query("  cash relief  ")
    embedder.embed_query("cash relief")
    assert embedder.encode_calls == 1


def test_the_cache_is_bounded() -> None:
    embedder = _CountingEmbedder()
    for index in range(200):
        embedder.embed_query(f"query {index}")
    assert len(embedder._cache) <= 64


def test_concurrent_callers_do_not_corrupt_the_cache() -> None:
    """Query variants are retrieved concurrently on real threads."""

    embedder = _CountingEmbedder()
    errors: list[BaseException] = []

    def work(index: int) -> None:
        try:
            for _ in range(40):
                embedder.embed_queries([f"q{index}", f"q{(index + 1) % 8}", "shared"])
        except BaseException as error:  # noqa: BLE001 - recorded and re-raised below
            errors.append(error)

    threads = [threading.Thread(target=work, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors
    assert len(embedder._cache) <= 64


def test_eviction_keeps_the_most_recently_used_query() -> None:
    embedder = _CountingEmbedder()
    embedder.embed_query("keep me")
    for index in range(100):
        embedder.embed_query(f"query {index}")
        embedder.embed_query("keep me")
    assert "keep me" in embedder._cache
