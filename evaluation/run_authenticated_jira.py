"""Serial Jira evaluation through the public, user-authenticated backend.

The operator installs a pinned target; this client can submit only its opaque
dataset reference and case IDs. It never supplies collection names or policies.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import time

import httpx


def save(path, result):
    temporary = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def candidate_hit(case, documents):
    return any(
        all(
            str(document.get(predicate["field"], "")) == str(predicate["equals"])
            for predicate in alternative["all_of"]
        )
        for alternative in case.get("gold_match", {}).get("any_of", [])
        for document in documents
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default="http://127.0.0.1:8001")
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    target = json.loads(args.target.read_text())
    reuse_identical = target.get("reuseIdenticalQuestions") is True
    cases = [json.loads(line) for line in args.cases.read_text().splitlines() if line.strip()]
    if not 1 <= len(cases) <= 100:
        raise ValueError("Each evaluation dataset must contain 1–100 cases")
    result = {
        "project_id": target["projectId"],
        "dataset_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "dataset_reference": target["datasetReference"],
        "cases": [],
        "status": "RUNNING",
        "expected_case_count": len(cases),
        "authorization": "user bearer token; backend Graph authorization",
        "grounded_answer_accuracy": None,
        "production_modified": False,
    }
    if args.run_id and args.out.exists():
        previous = json.loads(args.out.read_text())
        if (previous.get("reuse_identical_questions") is True) != reuse_identical:
            raise ValueError("Resume requires the same benchmark reuse setting")
        if (
            any(
                previous.get(field) != result[field]
                for field in ("project_id", "dataset_sha256", "dataset_reference")
            )
            or previous.get("run_id") != args.run_id
        ):
            raise ValueError("Resume requires the same run, target, and dataset")
        result["cases"] = previous["cases"]
    completed_ids = {row["id"] for row in result["cases"]}
    questions_by_id = {case["id"]: case["question"] for case in cases}
    measured_questions = (
        {questions_by_id[row["id"]]: row for row in result["cases"]} if reuse_identical else {}
    )
    result["reuse_identical_questions"] = reuse_identical
    with httpx.Client(timeout=250) as client:

        def headers():
            session = json.loads(args.session.read_text())
            if session["expires_at"] <= time.time() + 260:
                raise RuntimeError(
                    "User authorization requires refresh before the next bounded case"
                )
            return {"Authorization": "Bearer " + session["access_token"]}

        if args.run_id:
            run_id = args.run_id
        else:
            response = client.post(
                args.backend + "/v1/evaluations",
                headers=headers(),
                json={
                    "projectId": target["projectId"],
                    "datasetReference": target["datasetReference"],
                    "evaluatorSuiteVersion": "2026-09-10.1",
                    "candidateConfiguration": {
                        "promptVersion": "configured-runtime",
                        "modelVersion": "configured-runtime",
                        "modelProfile": "standard",
                        "retrievalTopK": 25,
                        "rerankTopN": 8,
                        "retrievalScoreThreshold": 0.0,
                    },
                },
            )
            response.raise_for_status()
            run_id = response.json()["runId"]
        result["run_id"] = run_id
        save(args.out, result)
        for case in cases:
            if case["id"] in completed_ids:
                continue
            began = time.monotonic()
            try:
                shared = measured_questions.get(case["question"]) if reuse_identical else None
                if shared:
                    # Offline benchmark reuse: another gold label evaluates the
                    # same captured answer, not another authorized application call.
                    body = shared["response"]
                else:
                    response = client.post(
                        args.backend + f"/v1/evaluations/{run_id}/cases/{case['id']}",
                        headers=headers(),
                    )
                    response.raise_for_status()
                    body = response.json()
                evidence = body.get("evaluationEvidence") or {}
                row = {
                    "id": case["id"],
                    "language": case["query_language"],
                    "suite": case["suite"],
                    "answerable": case["answerable"],
                    "duration_seconds": round(time.monotonic() - began, 3),
                    "http_status": None if shared else response.status_code,
                    "response": body,
                    "shared_response_from": shared["id"] if shared else None,
                    "candidate_hit": candidate_hit(case, evidence.get("candidates", []))
                    if case["answerable"]
                    else None,
                    "selected_hit": candidate_hit(case, evidence.get("selected", []))
                    if case["answerable"]
                    else None,
                    "diagnostics_complete": bool(evidence) and evidence.get("overflow") is False,
                }
                result["cases"].append(row)
                if reuse_identical:
                    measured_questions.setdefault(case["question"], row)
                print(
                    json.dumps(
                        {
                            k: row[k]
                            for k in ("id", "duration_seconds", "candidate_hit", "selected_hit")
                        }
                    ),
                    flush=True,
                )
                save(args.out, result)
                if case["suite"].startswith("jira_current") and (
                    body.get("status") != "ANSWERED" or row["selected_hit"] is not True
                ):
                    result.update(
                        status="STOPPED_QUALITY_GATE_FAILURE",
                        failed_case=case["id"],
                        failure_type="CurrentIssueEvidenceNotRetained",
                    )
                    save(args.out, result)
                    return
            except Exception as failure:
                result.update(
                    status="BLOCKED", failed_case=case["id"], failure_type=type(failure).__name__
                )
                save(args.out, result)
                raise
    result["unique_case_requests"] = sum(
        not row.get("shared_response_from") for row in result["cases"]
    )
    result["status"] = "EXECUTION_COMPLETE_REVIEW_PENDING"
    save(args.out, result)


if __name__ == "__main__":
    main()
