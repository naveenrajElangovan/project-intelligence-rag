"""Audit measured Jira retrieval and citation identities; never invent semantic scores."""

import argparse
from collections import Counter
import json
from pathlib import Path


def audit(results, cases, records):
    gold = {case["id"]: case for case in cases}
    identities = {
        (r["metadata"].get("source_id"), r["metadata"].get("locator")): r for r in records
    }
    citation_map = {}
    for identity, record in identities.items():
        m = record["metadata"]
        citation_map.setdefault((m.get("source_url"), m.get("locator")), set()).add(identity)
    rows = []
    invalid_citations = 0
    citation_count = 0
    unauthorized = 0
    for row in results["cases"]:
        case = gold[row["id"]]
        expected = set()
        for alternative in case.get("gold_match", {}).get("any_of", []):
            predicates = {p["field"]: str(p["equals"]) for p in alternative["all_of"]}
            expected.add((predicates["source_id"], predicates["locator"]))
        response = row["response"]
        actual = set()
        invalid = []
        for citation in response.get("citations") or []:
            citation_count += 1
            matches = citation_map.get((citation.get("url"), citation.get("locator")), set())
            if matches:
                actual.update(matches)
            else:
                invalid_citations += 1
                invalid.append(citation)
        evidence = response.get("evaluationEvidence") or {}
        for item in [*evidence.get("candidates", []), *evidence.get("selected", [])]:
            if (
                item.get("project_id") != results["project_id"]
                or item.get("access_policy_id") != f"project:{results['project_id']}"
            ):
                unauthorized += 1
        rows.append(
            {
                "id": row["id"],
                "language": row["language"],
                "suite": row["suite"],
                "answerable": case["answerable"],
                "status": response.get("status"),
                "candidate_hit": row["candidate_hit"],
                "selected_hit": row["selected_hit"],
                "final_evidence_hit": bool(expected & actual) if case["answerable"] else None,
                "gold_resolved": all(identity in identities for identity in expected),
                "invalid_citations": invalid,
                "semantic_review": "PENDING",
            }
        )
    positive = [r for r in rows if r["answerable"]]
    return {
        "run_id": results["run_id"],
        "execution_status": results["status"],
        "completed_cases": len(rows),
        "expected_cases": len(cases),
        "candidate_recall": sum(r["candidate_hit"] is True for r in positive) / len(positive)
        if positive
        else None,
        "final_evidence_recall": sum(r["final_evidence_hit"] is True for r in positive)
        / len(positive)
        if positive
        else None,
        "citation_identity_correctness": 1 - invalid_citations / citation_count
        if citation_count
        else None,
        "citation_count": citation_count,
        "unauthorized_captured_identities": unauthorized,
        "gold_resolution": sum(r["gold_resolved"] for r in rows) / len(rows) if rows else None,
        "answer_status_counts": dict(Counter(r["status"] for r in rows)),
        "grounded_answer_accuracy": None,
        "citation_semantic_correctness": None,
        "non_jira_regression": None,
        "promoted": False,
        "cases": rows,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("results", "cases", "evidence", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    result = audit(
        json.loads(args.results.read_text()),
        [json.loads(line) for line in args.cases.read_text().splitlines() if line.strip()],
        json.loads(args.evidence.read_text()),
    )
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "cases"}))
