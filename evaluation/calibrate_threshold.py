"""Choose the lowest rerank threshold keeping no-answer false positives <= 5%."""

import argparse
import json
from pathlib import Path


def calibrate(rows: list[dict[str, object]]) -> float:
    negatives = [float(row["max_rerank_score"]) for row in rows if not row["answerable"]]
    candidates = sorted({0.0, 0.35, 1.0, *(float(row["max_rerank_score"]) for row in rows)})
    for threshold in candidates:
        rate = sum(score >= threshold for score in negatives) / len(negatives) if negatives else 0
        if rate <= 0.05:
            return threshold
    return 1.0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("labels", type=Path)
    arguments = parser.parse_args()
    rows = [json.loads(line) for line in arguments.labels.read_text(encoding="utf-8").splitlines() if line]
    print(json.dumps({"rerank_threshold": calibrate(rows)}))
