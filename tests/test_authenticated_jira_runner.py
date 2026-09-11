import hashlib
import json
import sys
import time
from evaluation.run_authenticated_jira import main


def test_resume_keeps_completed_cases_without_repeating_requests(tmp_path, monkeypatch):
    cases = [
        {
            "id": str(i),
            "project_id": "APP",
            "question": "Describe OPS-1",
            "query_language": "en",
            "suite": "jira_description",
            "answerable": True,
            "gold_match": {"any_of": []},
        }
        for i in [1, 2]
    ]
    paths = {name: tmp_path / name for name in ["cases", "target", "session", "out"]}
    paths["cases"].write_text("".join(json.dumps(c) + "\n" for c in cases))
    paths["target"].write_text(
        json.dumps({"projectId": "APP", "datasetReference": "staging:opaque"})
    )
    paths["session"].write_text(
        json.dumps({"access_token": "test-only", "expires_at": time.time() + 1000})
    )
    paths["out"].write_text(
        json.dumps(
            {
                "run_id": "run",
                "project_id": "APP",
                "dataset_reference": "staging:opaque",
                "dataset_sha256": hashlib.sha256(paths["cases"].read_bytes()).hexdigest(),
                "cases": [{"id": "1", "preserved": True}],
            }
        )
    )
    calls = []

    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"status": "INSUFFICIENT_EVIDENCE", "evaluationEvidence": {"overflow": False}}

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            calls.append(url)
            return Response()

    monkeypatch.setattr("evaluation.run_authenticated_jira.httpx.Client", Client)
    argv = ["runner", "--run-id", "run"]
    for name, path in paths.items():
        argv.extend(["--" + name, str(path)])
    monkeypatch.setattr(sys, "argv", argv)
    main()
    assert calls == ["http://127.0.0.1:8001/v1/evaluations/run/cases/2"]
    result = json.loads(paths["out"].read_text())
    assert result["cases"][0] == {"id": "1", "preserved": True}
    assert len(result["cases"]) == 2


def test_explicit_offline_reuse_keeps_both_gold_cases_and_marks_one_real_request(
    tmp_path, monkeypatch
):
    cases = [
        {
            "id": str(i),
            "project_id": "APP",
            "question": "Describe the event",
            "query_language": "en",
            "suite": "bilingual_curated",
            "answerable": True,
            "gold_match": {"any_of": []},
        }
        for i in [1, 2]
    ]
    paths = {name: tmp_path / name for name in ["cases", "target", "session", "out"]}
    paths["cases"].write_text("".join(json.dumps(c) + "\n" for c in cases))
    paths["target"].write_text(
        json.dumps(
            {
                "projectId": "APP",
                "datasetReference": "staging:opaque",
                "reuseIdenticalQuestions": True,
            }
        )
    )
    paths["session"].write_text(
        json.dumps({"access_token": "test-only", "expires_at": time.time() + 1000})
    )
    calls = []

    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "runId": "run",
                "status": "INSUFFICIENT_EVIDENCE",
                "evaluationEvidence": {"overflow": False},
            }

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            calls.append(url)
            return Response()

    monkeypatch.setattr("evaluation.run_authenticated_jira.httpx.Client", Client)
    argv = ["runner"]
    for name, path in paths.items():
        argv.extend(["--" + name, str(path)])
    monkeypatch.setattr(sys, "argv", argv)
    main()
    assert len(calls) == 2  # Run creation plus one actual case request.
    result = json.loads(paths["out"].read_text())
    assert len(result["cases"]) == 2 and result["unique_case_requests"] == 1
    assert result["cases"][1]["shared_response_from"] == "1"
    assert result["cases"][1]["http_status"] is None
