"""Keep the RAG repository's pre-existing Ruff lint debt from growing."""

from __future__ import annotations

import json
import subprocess
import sys

BASELINE_ERROR_COUNT = 109
TARGETS = ("app", "evaluation", "tests", "scripts")


def main() -> int:
    """Run Ruff over all Python sources and reject an increased violation count."""

    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--output-format=json", *TARGETS],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
    try:
        violations = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        print("Ruff lint check did not produce valid JSON.", file=sys.stderr)
        return result.returncode or 1
    if not isinstance(violations, list):
        print("Ruff lint check returned an unexpected result.", file=sys.stderr)
        return 1
    for violation in violations:
        filename = violation.get("filename", "unknown")
        location = violation.get("location", {})
        print(
            f"{filename}:{location.get('row', 0)}:{location.get('column', 0)}: "
            f"{violation.get('code', '')} {violation.get('message', '')}"
        )
    count = len(violations)
    print(f"Ruff lint ratchet: {count} current errors; maximum {BASELINE_ERROR_COUNT}")
    if count > BASELINE_ERROR_COUNT:
        print("Ruff lint debt increased; fix new violations before merging.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
