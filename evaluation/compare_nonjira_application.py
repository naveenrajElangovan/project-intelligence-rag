"""Compare identical non-Jira cases through production and staged application paths.

Scores describe returned evidence and abstention, not semantic answer accuracy.
Only sources on a SUFFICIENT answer count as final answer evidence.
"""

import argparse
import json
from pathlib import Path

from app.llm import refusal_answer, insufficient_evidence_answer

_REFUSAL_REASONS = (
    "NO_ACCESS",
    "INSUFFICIENT_EVIDENCE",
    "UNVERIFIED_EVIDENCE",
    "POPULATION_RETRIEVAL_MISS",
    "UNRESOLVED_SOURCE_CONFLICT",
    "SOURCE_SCOPE_VIOLATION",
    "PERMISSIONS_NOT_SATISFIED",
    "FRESHNESS_NOT_VERIFIABLE",
    "REQUESTED_COVERAGE_INCOMPLETE",
    "UNSUPPORTED_CLAIM",
    "INVALID_DERIVATION",
    "TEMPORARILY_UNAVAILABLE",
)
_VERIFIED_REFUSALS = {
    refusal_answer(reason, language) for reason in _REFUSAL_REASONS for language in ("en", "es")
} | {insufficient_evidence_answer(language) for language in ("en", "es")}


def reference_identity(value):
    return tuple(
        str(value.get(name) or "") for name in ("type", "title", "reference", "url", "locator")
    )


def compare(cases, records, baseline, staged):
    ids = {c["id"] for c in cases}
    old = {r["id"]: r for r in baseline["cases"]}
    new = {r["id"]: r for r in staged["cases"]}
    if (
        len(ids) != len(cases)
        or set(old) != ids
        or set(new) != ids
        or not baseline["status"].startswith("EXECUTION_COMPLETE")
        or not staged["status"].startswith("EXECUTION_COMPLETE")
    ):
        raise ValueError("Both application runs must complete the identical dataset")
    source_map = {}
    for item in records:
        m = item["metadata"]
        key = reference_identity(
            {
                "type": m.get("source_type"),
                "title": m.get("title"),
                "reference": m.get("reference"),
                "url": m.get("source_url"),
                "locator": m.get("locator"),
            }
        )
        source_map.setdefault(key, []).append(m)

    def measured(case, row):
        body = row["response"]
        enough = body.get("evidenceStatus") == "SUFFICIENT"
        sources = body.get("sources") or []
        docs = (
            [doc for source in sources for doc in source_map.get(reference_identity(source), [])]
            if enough
            else []
        )
        hit = (
            any(
                all(str(doc.get(p["field"]) or "") == str(p["equals"]) for p in alt["all_of"])
                for alt in case["gold_match"]["any_of"]
                for doc in docs
            )
            if case["answerable"]
            else None
        )
        # Normal chat retains unverified source cards on a refusal. Those are
        # not final answer citations and do not negate an explicit refusal.
        abstained = (
            not enough
            and body.get("confidence") == "NONE"
            and body.get("answer") in _VERIFIED_REFUSALS
        )
        return {
            "gold_final_evidence_hit": hit,
            "verified_abstention": abstained,
            "evidence_or_abstention_correct": hit if case["answerable"] else abstained,
            "unresolved_source_references": sum(
                reference_identity(source) not in source_map for source in sources
            ),
        }

    rows = [
        {
            "id": c["id"],
            "language": c["query_language"],
            "answerable": c["answerable"],
            "baseline": measured(c, old[c["id"]]),
            "staged": measured(c, new[c["id"]]),
        }
        for c in cases
    ]
    groups = {}
    regressions = []
    for language in ("all", "en", "es"):
        group = [r for r in rows if language == "all" or r["language"] == language]
        metrics = {}
        for metric, selected in [
            ("evidence_or_abstention_correct", group),
            ("gold_final_evidence_hit", [r for r in group if r["answerable"]]),
            ("verified_abstention", [r for r in group if not r["answerable"]]),
        ]:
            if not selected:
                continue
            before = sum(r["baseline"][metric] is True for r in selected) / len(selected)
            after = sum(r["staged"][metric] is True for r in selected) / len(selected)
            regression = 100 * (before - after)
            regressions.append(regression)
            metrics[metric] = {
                "cases": len(selected),
                "baseline": before,
                "staged": after,
                "regression_percentage_points": regression,
            }
        groups[language] = metrics
    return {
        "cases": len(rows),
        "unique_questions": len({c["question"] for c in cases}),
        "maximum_regression_percentage_points": max(regressions),
        "by_language": groups,
        "cases_detail": rows,
        "method": "Same source-anchored suite through authorized production chat and staged application evaluation. Final-source recall and abstention only; not a semantic answer score.",
        "passed": max(regressions) <= 5,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cases", "evidence", "baseline", "staged", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    a = parser.parse_args()
    result = compare(
        [json.loads(x) for x in a.cases.read_text().splitlines()],
        json.loads(a.evidence.read_text()),
        json.loads(a.baseline.read_text()),
        json.loads(a.staged.read_text()),
    )
    a.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "cases_detail"}))
