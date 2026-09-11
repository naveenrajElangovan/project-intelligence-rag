"""Serial baseline through normal application chat, using the real user account.

Identical questions share one measured response; every original gold case stays
in the output. These are isolated test conversations, whose IDs are recorded.
No production route or indexed content is changed.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import httpx

from evaluation.run_authenticated_jira import save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default="http://127.0.0.1:8001")
    parser.add_argument("--project", required=True)
    for name in ("cases", "session", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    cases = [json.loads(line) for line in args.cases.read_text().splitlines() if line.strip()]
    if not cases or any(case["project_id"] != args.project for case in cases):
        raise ValueError("Dataset must belong to the selected project")
    fingerprint = hashlib.sha256(args.cases.read_bytes()).hexdigest()
    result = {
        "project_id": args.project,
        "dataset_sha256": fingerprint,
        "status": "RUNNING",
        "cases": [],
        "production_modified": False,
        "path": "public application chat; existing production collection mapping",
    }
    if args.out.exists():
        previous = json.loads(args.out.read_text())
        if previous["project_id"] != args.project or previous["dataset_sha256"] != fingerprint:
            raise ValueError("Resume dataset does not match")
        if previous.get("pending_request"):
            raise ValueError(
                "Previous request has an uncertain outcome; inspect it before starting a new baseline"
            )
        result["cases"] = previous["cases"]
    completed = {row["id"] for row in result["cases"]}
    measured = {row["question"]: row for row in result["cases"]}
    with httpx.Client(timeout=250) as client:
        for case in cases:
            if case["id"] in completed:
                continue
            began = time.monotonic()
            shared = measured.get(case["question"])
            try:
                if shared:
                    body = shared["response"]
                else:
                    session = json.loads(args.session.read_text())
                    if session["expires_at"] <= time.time() + 260:
                        raise RuntimeError("Developer authorization needs renewal")
                    result["pending_request"] = case["id"]
                    save(args.out, result)
                    response = client.post(
                        args.backend + f"/v1/projects/{args.project}/chat",
                        headers={"Authorization": "Bearer " + session["access_token"]},
                        json={"question": case["question"], "mode": "ANALYZE"},
                    )
                    response.raise_for_status()
                    body = response.json()
                    result["pending_request"] = None
                row = {
                    "id": case["id"],
                    "question": case["question"],
                    "language": case["query_language"],
                    "response": body,
                    "shared_response_from": shared["id"] if shared else None,
                    "duration_seconds": round(time.monotonic() - began, 3),
                }
                result["cases"].append(row)
                measured.setdefault(case["question"], row)
                save(args.out, result)
                print(
                    json.dumps(
                        {
                            "id": case["id"],
                            "confidence": body.get("confidence"),
                            "shared": bool(shared),
                        }
                    ),
                    flush=True,
                )
            except Exception as error:
                result.update(
                    status="BLOCKED", failed_case=case["id"], failure_type=type(error).__name__
                )
                save(args.out, result)
                raise
    result["status"] = "EXECUTION_COMPLETE_REVIEW_PENDING"
    result["unique_requests"] = len(measured)
    save(args.out, result)


if __name__ == "__main__":
    main()
