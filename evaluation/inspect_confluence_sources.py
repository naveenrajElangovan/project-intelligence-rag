"""Print compact fact candidates from an authorized Confluence page-list response.

The script reads Confluence v2 JSON from stdin. It never prints credentials and keeps
page bodies out of persistent evaluation fixtures.
"""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
import re
import sys


class _TextExtractor(HTMLParser):
    _BLOCKS = {
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
        "pre",
        "td",
        "th",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def lines(self) -> list[str]:
        return [
            normalized
            for value in "".join(self.parts).splitlines()
            if (normalized := re.sub(r"\s+", " ", value).strip())
        ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", action="append", required=True)
    parser.add_argument(
        "--pattern",
        default=(
            r"observed|workflow|entry point|responsib|architecture|source files|"
            r"nonblank|line count|screen|viewmodel|repository|use case|endpoint|"
            r"navigation|error|state|dependency"
        ),
    )
    parser.add_argument("--limit", type=int, default=80)
    arguments = parser.parse_args()
    wanted = set(arguments.title)
    pattern = re.compile(arguments.pattern, re.IGNORECASE)
    payload = json.load(sys.stdin)
    pages = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(pages, list):
        raise SystemExit("Confluence returned no page-list results.")
    matched = 0
    for page in pages:
        if not isinstance(page, dict) or page.get("title") not in wanted:
            continue
        matched += 1
        body = page.get("body") if isinstance(page.get("body"), dict) else {}
        storage = body.get("storage") if isinstance(body.get("storage"), dict) else {}
        extractor = _TextExtractor()
        extractor.feed(str(storage.get("value") or ""))
        print(f"## {page['title']} (page {page.get('id')})", flush=True)
        count = 0
        for line in extractor.lines():
            if pattern.search(line):
                print(line, flush=True)
                count += 1
                if count >= arguments.limit:
                    break
    missing = wanted - {
        str(page.get("title")) for page in pages if isinstance(page, dict)
    }
    if missing:
        raise SystemExit(f"Missing requested pages: {sorted(missing)}")
    if matched != len(wanted):
        raise SystemExit("Duplicate or missing page titles prevented exact selection.")


if __name__ == "__main__":
    main()
