"""Read-only client for freshness-sensitive Atlassian MCP verification.

Indexed Chroma evidence remains the default. This client is intentionally
separate so disabling the feature produces no Atlassian network calls and does
not alter GitHub or non-live Confluence retrieval.
"""

from typing import Any

import httpx


class AtlassianLiveClient:
    def __init__(self, base_url: str, api_key: str, timeout_seconds: float = 20.0):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._api_key)

    async def search(
        self,
        *,
        project_id: str,
        user_id: str,
        tool: str,
        query: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Atlassian live verification is not configured.")
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/v1/internal/search",
                headers={"X-Internal-Api-Key": self._api_key},
                json={
                    "projectId": project_id,
                    "userId": user_id,
                    "identityClass": "USER",
                    "tool": tool,
                    "query": query,
                    "arguments": arguments,
                },
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Atlassian service returned malformed MCP data.")
        return payload
