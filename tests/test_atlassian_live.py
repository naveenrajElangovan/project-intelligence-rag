import asyncio

import httpx

from app.providers.atlassian_live import AtlassianLiveClient


def test_user_identity_is_forwarded_without_service_fallback(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"complete": True, "content": []}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, headers, json):
            captured.update(json)
            return Response()

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    client = AtlassianLiveClient("http://atlassian:8000", "secret")
    result = asyncio.run(client.search(project_id="P1", user_id="U1", tool="search", query="T0-7", arguments={}))
    assert result["complete"] is True
    assert captured["identityClass"] == "USER"
    assert captured["userId"] == "U1"
