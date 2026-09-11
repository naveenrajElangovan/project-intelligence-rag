"""Verify exact current-status answers, including any source-supported priority."""

import argparse
import json
from pathlib import Path


def audit(results, cases, records):
    case_map = {c["id"]: c for c in cases}
    current = {
        (r["metadata"]["source_id"], r["metadata"]["locator"]): r
        for r in records
        if r["metadata"].get("jira_chunk_kind") == "CURRENT"
    }
    rows = []
    issues = set()
    for row in results["cases"]:
        case = case_map[row["id"]]
        predicates = {p["field"]: p["equals"] for p in case["gold_match"]["any_of"][0]["all_of"]}
        doc = current[(predicates["source_id"], predicates["locator"])]
        issues.add(predicates["source_id"])
        fields = json.loads(doc["document"].split("Current issue fields:\n", 1)[1])
        status = fields["status"]["name"]
        priority = (fields.get("priority") or {}).get("name")
        title = doc["metadata"]["title"]
        expected = (
            f"The status of '{title}' is '{status}'"
            if row["language"] == "en"
            else f"El estado de '{title}' es '{status}'"
        )
        allowed = {expected + "."}
        if priority:
            allowed.add(
                expected
                + (
                    f" with {priority.lower()} priority."
                    if row["language"] == "en"
                    else f" con prioridad {priority}."
                )
            )
        body = row["response"]
        citations = body.get("citations") or []
        correct = (
            status == case["expected_current_status"]
            and body.get("status") == "ANSWERED"
            and body["answer"] in allowed
            and bool(citations)
            and all(
                c.get("locator") == doc["metadata"]["locator"]
                and c.get("url") == doc["metadata"]["source_url"]
                for c in citations
            )
            and row["selected_hit"]
        )
        rows.append(
            {
                "id": row["id"],
                "expected_status": status,
                "source_priority": priority,
                "correct": bool(correct),
            }
        )
    if len(rows) != len(cases) or not results["status"].startswith("EXECUTION_COMPLETE"):
        raise ValueError("Status execution incomplete")
    return {
        "run_id": results["run_id"],
        "cases": len(rows),
        "correct": sum(r["correct"] for r in rows),
        "accuracy": sum(r["correct"] for r in rows) / len(rows),
        "distinct_issues": len(issues),
        "statuses": sorted({r["expected_status"] for r in rows}),
        "method": "Exact current-state answer and citation comparison; an optional priority must also match the current source.",
        "case_results": rows,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for name in ("results", "cases", "evidence", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    result = audit(
        json.loads(a.results.read_text()),
        [json.loads(x) for x in a.cases.read_text().splitlines()],
        json.loads(a.evidence.read_text()),
    )
    a.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "case_results"}))
