import json

import pytest

from evaluation.run_ragas_eval import load_samples, publish_scores_to_phoenix


def test_ragas_dataset_requires_content_and_reference(tmp_path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "user_input": "question",
                "response": "answer",
                "retrieved_contexts": ["evidence"],
                "reference": "expected answer",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert load_samples(dataset)[0]["reference"] == "expected answer"


def test_ragas_dataset_rejects_missing_reference(tmp_path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text('{"user_input":"q","response":"a","retrieved_contexts":[]}\n')
    with pytest.raises(ValueError, match="reference"):
        load_samples(dataset)


def test_phoenix_annotations_contain_scores_but_no_rag_content(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("evaluation.run_ragas_eval.urlopen", fake_urlopen)
    publish_scores_to_phoenix("http://phoenix:6006", "0123456789abcdef", {"faithfulness": 0.9}, 4)

    assert captured["url"] == "http://phoenix:6006/v1/span_annotations?sync=true"
    annotation = captured["body"]["data"][0]
    assert annotation["span_id"] == "0123456789abcdef"
    assert annotation["result"] == {"score": 0.9}
    assert "user_input" not in json.dumps(captured["body"])
