from evaluation.run_reproducibility_probe import _fingerprint


def test_fingerprint_ignores_json_order_but_includes_public_answer_contract() -> None:
    first = {
        "status": "ANSWERED",
        "answer": "Verified answer",
        "confidence": "HIGH",
        "sources": [{"title": "Guide", "chunkId": "c1", "sourceId": "s1"}],
    }
    reordered = {
        "sources": [{"sourceId": "s1", "chunkId": "c1", "title": "Guide"}],
        "confidence": "HIGH",
        "answer": "Verified answer",
        "status": "ANSWERED",
    }

    assert _fingerprint(first) == _fingerprint(reordered)
    assert _fingerprint({**first, "answer": "Different"}) != _fingerprint(first)
