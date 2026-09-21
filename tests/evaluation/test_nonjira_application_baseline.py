import json
import sys
import time
from evaluation import run_nonjira_application_baseline as runner


def test_duplicate_questions_and_resume_do_not_repeat_model_requests(tmp_path, monkeypatch):
    cases = tmp_path / "cases.jsonl"
    cases.write_text(
        "\n".join(
            json.dumps(
                {
                    "id": key,
                    "project_id": "APP",
                    "query_language": "en",
                    "question": "What is EVENT_A?",
                }
            )
            for key in ["one", "two"]
        )
    )
    session = tmp_path / "session.json"
    session.write_text(json.dumps({"access_token": "test-only", "expires_at": time.time() + 3600}))
    out = tmp_path / "out.json"
    calls = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            calls.append((url, kwargs["json"]))

            class Response:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {
                        "confidence": "HIGH",
                        "answer": "Evidence",
                        "conversationId": "test-conversation",
                    }

            return Response()

    monkeypatch.setattr(runner.httpx, "Client", Client)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "baseline",
            "--project",
            "APP",
            "--cases",
            str(cases),
            "--session",
            str(session),
            "--out",
            str(out),
        ],
    )
    runner.main()
    runner.main()
    result = json.loads(out.read_text())
    assert len(calls) == 1
    assert len(result["cases"]) == 2
    assert result["cases"][1]["shared_response_from"] == "one"
    assert result["unique_requests"] == 1
