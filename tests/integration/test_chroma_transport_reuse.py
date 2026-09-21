from unittest.mock import Mock
import chromadb
import httpx
from types import SimpleNamespace
from app import retrieval


def test_snapshot_and_health_transport_can_share_existing_retrieval_client(monkeypatch):
    factory = Mock(
        side_effect=lambda **kwargs: SimpleNamespace(
            _server=SimpleNamespace(
                _session=httpx.Client(
                    transport=httpx.MockTransport(lambda request: httpx.Response(200))
                )
            )
        )
    )
    monkeypatch.setattr(chromadb, "HttpClient", factory)
    monkeypatch.setattr(retrieval, "_CHROMA_CLIENTS", {})
    one = retrieval.shared_chroma_client("CHROMA.", 8000)
    for _ in range(100):
        assert retrieval.shared_chroma_client("chroma", 8000) is one
    assert retrieval.shared_chroma_client("chroma", 8001) is not one
    assert factory.call_count == 2


def test_shared_client_bounds_blocking_socket_reads(monkeypatch):
    client = SimpleNamespace(_server=SimpleNamespace(_session=httpx.Client(timeout=None)))
    monkeypatch.setattr(chromadb, "HttpClient", lambda **kwargs: client)
    monkeypatch.setattr(retrieval, "_CHROMA_CLIENTS", {})
    retrieval.shared_chroma_client("example", 8000)
    assert client._server._session.timeout.read == 15.0
    assert client._server._session.timeout.connect == 5.0
    assert client._server._session.timeout.pool == 5.0
    client._server._session.close()
