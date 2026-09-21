import json

import httpx

from app.telemetry import ollama_payload_fingerprint


def test_ollama_payload_fingerprint_is_content_free_and_byte_sensitive() -> None:
    payload = {
        "model": "model",
        "messages": [{"role": "user", "content": "private evidence"}],
        "stream": True,
        "think": False,
        "format": {"type": "object"},
        "options": {"seed": 0, "temperature": 0.0, "top_k": 1, "num_thread": 8},
    }
    first = httpx.Request("POST", "http://ollama/api/chat", json=payload)
    second = httpx.Request("POST", "http://ollama/api/chat", content=json.dumps(payload).encode())

    first_result = ollama_payload_fingerprint(first)
    second_result = ollama_payload_fingerprint(second)

    assert first_result["canonical_payload_sha256"] == second_result["canonical_payload_sha256"]
    assert first_result["payload_sha256"] != second_result["payload_sha256"]
    assert first_result["messages_sha256"] == second_result["messages_sha256"]
    assert first_result["prompt_sha256"] == second_result["prompt_sha256"]
    assert first_result["method"] == "POST"
    assert first_result["path"] == "/api/chat"
    assert first_result["options"] == {
        "num_thread": 8,
        "seed": 0,
        "temperature": 0.0,
        "top_k": 1,
    }
    assert "private evidence" not in json.dumps(first_result)
