"""Keep the RAG repository's pre-existing Ruff formatting debt from growing."""

from __future__ import annotations

import re
import subprocess
import sys

BASELINE_UNFORMATTED_FILES = 116
SUMMARY_PATTERN = re.compile(r"(\d+) files? would be reformatted")
TARGETS = ("app", "evaluation", "tests", "scripts")


def main() -> int:
    """Run Ruff format in check mode and reject newly unformatted files."""

    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", *TARGETS],
        check=False,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    if result.returncode == 0:
        count = 0
    elif match := SUMMARY_PATTERN.search(output):
        count = int(match.group(1))
    else:
        print("Ruff format check did not produce a recognized result.", file=sys.stderr)
        return result.returncode or 1
    print(f"Ruff format ratchet: {count} current files; maximum {BASELINE_UNFORMATTED_FILES}")
    if count > BASELINE_UNFORMATTED_FILES:
        print("Ruff formatting debt increased; format changed files.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
