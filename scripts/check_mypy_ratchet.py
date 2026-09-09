"""Keep the RAG repository's known mypy error count from growing."""

from __future__ import annotations

import re
import subprocess
import sys

BASELINE_ERROR_COUNT = 473
ERROR_PATTERN = re.compile(r"^.+:\d+: error:", re.MULTILINE)


def main() -> int:
    """Run whole-application mypy and reject any increase in known errors."""

    result = subprocess.run(
        [sys.executable, "-m", "mypy", "app", "--no-error-summary", "--no-pretty"],
        check=False,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    if result.returncode not in {0, 1}:
        print(f"mypy could not complete (exit {result.returncode}).", file=sys.stderr)
        return result.returncode
    count = len(ERROR_PATTERN.findall(output))
    print(f"mypy ratchet: {count} current errors; maximum {BASELINE_ERROR_COUNT}")
    if count > BASELINE_ERROR_COUNT:
        print("mypy error count increased; fix new errors before merging.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
