"""Run content-aware acceptance cases locally without exporting questions or answers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import time

import httpx

from app.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8003")
    parser.add_argument("--collection-name", default="project-intelligence")
    parser.add_argument("--project-id", required=True)
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).with_name("t2_live_acceptance.json"),
    )
    parser.add_argument("--id", action="append", dest="case_ids")
    parser.add_argument("--show-answer", action="store_true")
    arguments = parser.parse_args()
    settings = Settings()
    cases = json.loads(arguments.cases.read_text())
    if arguments.case_ids:
        selected = set(arguments.case_ids)
        cases = [case for case in cases if case["id"] in selected]
        missing = selected - {case["id"] for case in cases}
        if missing:
            raise SystemExit(f"Unknown case IDs: {sorted(missing)}")
    passed = 0
    headers = {}
    if settings.internal_api_key:
        headers["Authorization"] = f"Bearer {settings.internal_api_key}"
    with httpx.Client(timeout=180) as client:
        for case in cases:
            began = time.perf_counter()
            response = client.post(
                arguments.base_url.rstrip("/") + "/v1/answer",
                headers={**headers, "X-Request-ID": f"acceptance-{case['id']}"},
                json={
                    "projectId": arguments.project_id,
                    "collectionName": arguments.collection_name,
                    "textField": "chunk_text",
                    "embeddingField": "embedding_text",
                    "embeddingModel": "multilingual-e5-large",
                    "schemaVersion": "3",
                    "question": case["question"],
                    "accessPolicyIds": [f"project:{arguments.project_id}"],
                    "modelProfile": "budget",
                },
            )
            duration = time.perf_counter() - began
            payload = response.json() if response.status_code == 200 else {}
            answer = str(payload.get("answer") or "")
            confidence = str(payload.get("confidence") or "NONE")
            sources = payload.get("sources") or []
            if case["answerable"]:
                terms_ok = all(
                    _expected_term_present(str(term), answer)
                    for term in case["expected_terms"]
                )
                source_ok = any(
                    case["expected_source"].casefold()
                    in str(source.get("title") or "").casefold()
                    for source in sources
                )
                ok = response.status_code == 200 and confidence != "NONE" and terms_ok and source_ok
            else:
                ok = response.status_code == 200 and confidence == "NONE" and not sources
            passed += int(ok)
            print(
                f"{case['id']}: {'PASS' if ok else 'FAIL'} status={response.status_code} "
                f"confidence={confidence} sources={len(sources)} duration_s={duration:.2f}",
                flush=True,
            )
            if arguments.show_answer:
                if response.status_code == 200:
                    titles = [str(source.get("title") or "") for source in sources]
                    print(f"  answer={answer}", flush=True)
                    print(f"  source_titles={titles}", flush=True)
                else:
                    print(f"  error={response.text[:500]}", flush=True)
    print(
        f"SUMMARY passed={passed} total={len(cases)} rate={passed / len(cases):.1%}",
        flush=True,
    )
    raise SystemExit(0 if passed == len(cases) else 1)


def _expected_term_present(term: str, answer: str) -> bool:
    if term.casefold() in answer.casefold():
        return True
    if not re.fullmatch(r"\d+(?:[.,]\d+)*", term):
        return False
    expected = _canonical_number(term)
    return expected in {
        _canonical_number(value)
        for value in re.findall(r"(?<![\w])\d+(?:[.,]\d+)*(?![\w])", answer)
    }


def _canonical_number(value: str) -> str:
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", value):
        return re.sub(r"[.,]", "", value)
    return value.replace(",", ".")


if __name__ == "__main__":
    main()
