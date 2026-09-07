"""Create the review worksheet required before bilingual RAGAS can run."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    from evaluation.run_retrieval_eval import _load_evaluation_cases
except ModuleNotFoundError:  # Direct script execution.
    from run_retrieval_eval import _load_evaluation_cases


def build(cases: list[dict[str, object]], dataset_version: str) -> list[dict[str, object]]:
    return [
        {
            "case_id": case["id"],
            "query_language": case["query_language"],
            "target_evidence_language": case["target_evidence_language"],
            "question_for_review": case["question"],
            "question_sha256": hashlib.sha256(
                str(case["question"]).encode("utf-8")
            ).hexdigest(),
            "reference": "",
            "reference_status": "pending_review",
            "dataset_version": dataset_version,
        }
        for case in cases
        if case.get("suite") == "bilingual_curated"
        and case.get("answerable") is True
        and case.get("retired") is not True
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--suites",
        type=Path,
        default=Path(__file__).with_name("gold_suites.jsonl"),
        help=(
            "Evaluation suite. The default gold_suites.jsonl explicitly includes "
            "the companion bilingual_gold_suites.jsonl; passing the bilingual file "
            "directly limits the worksheet to that file."
        ),
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dataset-version", default="1")
    args = parser.parse_args()
    rows = build(_load_evaluation_cases(args.suites), args.dataset_version)
    args.out.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(f"wrote={args.out} references={len(rows)} status=pending_review")


if __name__ == "__main__":
    main()
