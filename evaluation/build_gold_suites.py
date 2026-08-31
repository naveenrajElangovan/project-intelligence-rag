"""Derive retrieval gold suites from the corpus, with no manual annotation.

Every case is a (question, gold predicate) pair. Predicates are declared against
chunk *metadata* -- specifically `structure_path` -- not against chunk ids,
because chunk ids change on every re-chunk and a hard-coded id list would rot the
first time chunker_version moves. The runner resolves predicates against a
namespace manifest at evaluation time, so one suite file survives re-indexing.

Deliberately NOT matched on `title`: the indexed title is the Confluence page
title ("Example Retail BOT/POS Event and Integration Contract"), which does not equal
the markdown filename. Matching on it would silently fail every case.

Document category is inferred with the same structural heuristics ingestion will
use, so running this doubles as a check on whether those heuristics classify the
corpus correctly before any Confluence label is written.

    python -m evaluation.build_gold_suites --corpus ~/Desktop/example-rag-corpus \
        --out evaluation/gold_suites.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ENTITY_HEADING = re.compile(
    r"^#{3}\s+`(?P<key>[A-Z][A-Z0-9_]*)`\s+[—-]\s+id\s+(?P<id>\d+),\s+version\s+(?P<version>[\d.]+)\s*$"
)
SECTION_HEADING = re.compile(r"^(?P<hashes>#{2,4})\s+\[(?P<sid>[A-Z]+-\d+)\]\s+(?P<title>.+?)\s*$")
ANY_HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.+?)\s*$")
REGISTRY_ROW = re.compile(r"^\|\s*`(?P<key>[A-Z][A-Z0-9_]{3,})`\s*\|")
ROW_EVENT_ID = re.compile(r"\|\s*(?P<id>\d{3})\s*\|")
ENTITY_HEADING_B = re.compile(
    r"^#{2,4}\s+[\d.]+\s+`(?P<key>[A-Z][A-Z0-9_]*)`\s+\(id\s+(?P<id>\d+)\)"
)


def entity_heading(line: str):
    return ENTITY_HEADING.match(line) or ENTITY_HEADING_B.match(line)

TABLE_ROW = re.compile(r"^\s*\|")
STEP_LINE = re.compile(r"^\s*\d+\.\s+\S")
NAVIGATIONAL = re.compile(
    r"\b(?:how to use|corpus|volume map|index|master index|placement|reading order|"
    r"what this volume|guide)\b",
    re.IGNORECASE,
)

# Structural thresholds. Chosen from the measured corpus and stated here so a
# misclassification is a tunable number rather than a mystery.
TABLE_DOMINANT_RATIO = 0.35   # table rows / total non-blank lines
ENTITY_SECTION_MINIMUM = 5    # entity-shaped H3 headings before it is a contract
STEP_DOMINANT_RATIO = 0.08


def infer_category(path: Path, lines: list[str]) -> tuple[str, str]:
    """Return (category, the evidence for it). Never guess silently."""
    body = [line for line in lines if line.strip()]
    total = max(len(body), 1)
    tables = sum(bool(TABLE_ROW.match(line)) for line in lines)
    entities = sum(bool(entity_heading(line)) for line in lines)
    steps = sum(bool(STEP_LINE.match(line)) for line in lines)
    headings = [ANY_HEADING.match(line) for line in lines]
    titles = " ".join(m.group("text") for m in headings if m)

    if entities >= ENTITY_SECTION_MINIMUM:
        return "entity-contract", f"{entities} entity-shaped H3 headings"
    if NAVIGATIONAL.search(path.stem) or (
        len(body) < 200 and len(NAVIGATIONAL.findall(titles)) >= 2
    ):
        return "index", f"navigational title/headings ({len(NAVIGATIONAL.findall(titles))} hits)"
    if tables / total >= TABLE_DOMINANT_RATIO:
        return "registry-table", f"{tables}/{total} lines are table rows"
    if steps / total >= STEP_DOMINANT_RATIO:
        return "workflow", f"{steps} numbered steps in {total} lines"
    if re.search(r"\bglossar|vocabular", titles, re.IGNORECASE):
        return "glossary", "glossary/vocabulary heading present"
    return "narrative", f"prose-dominant ({tables}/{total} table rows)"


def constant_forms(key: str) -> list[str]:
    """The documented convention: POS_CLOSE_SHIFT_EVENT is the Kotlin constant
    for wire name POS_CLOSE_SHIFT. Users type either, so both are tested."""
    return [key] if key.endswith("_EVENT") else [key, f"{key}_EVENT"]


def heading_paths(lines: list[str]) -> dict[int, list[str]]:
    stack: list[tuple[int, str]] = []
    out: dict[int, list[str]] = {}
    for index, line in enumerate(lines):
        match = ANY_HEADING.match(line)
        if match:
            level = len(match.group("hashes"))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, match.group("text").strip()))
        out[index] = [text for _level, text in stack]
    return out


_PROJECT_ID = ""


def case(cid, suite, question, contains, note, role, extras=None):
    row = {
        "id": cid,
        "suite": suite,
        "role": role,                       # answer_evidence | navigation
        "project_id": _PROJECT_ID,
        "question": question,
        "query_language": "en",
        "answerable": True,
        "gold_match": {"any_of": [{"field": "structure_path", "contains": c} for c in contains]},
        "derivation": note,
    }
    if extras:
        row.update(extras)
    return row


def build(corpus: Path, project_id: str) -> tuple[list[dict], list[tuple[str, str, str]]]:
    global _PROJECT_ID
    _PROJECT_ID = project_id
    rows: list[dict] = []
    classification: list[tuple[str, str, str]] = []
    seen_entities: set[str] = set()
    seen_sections: set[str] = set()
    seen_registry: set[str] = set()

    for path in sorted(corpus.glob("*.md")):
        lines = path.read_text(errors="ignore").splitlines()
        category, evidence = infer_category(path, lines)
        classification.append((path.name, category, evidence))
        paths = heading_paths(lines)
        # Index documents are navigation, not answer evidence. Asserting they must
        # be cited would contradict the profile that excludes them.
        role = "navigation" if category == "index" else "answer_evidence"

        for index, line in enumerate(lines):
            entity = entity_heading(line)
            if entity:
                key = entity.group("key")
                if key in seen_entities:
                    continue
                seen_entities.add(key)
                for form in constant_forms(key):
                    rows.append(case(
                        f"entity-{form}".lower(), "identifier_lookup",
                        f"What does the {form} event require?",
                        [f"`{key}`", key],
                        f"{path.name}:{index + 1} entity heading",
                        role,
                        {"expected_facts": [entity.group("id")] + (
                            [entity.group("version")]
                            if "version" in entity.groupdict() and entity.group("version")
                            else []),
                         "doc_category": category},
                    ))
                continue

            section = SECTION_HEADING.match(line)
            if section:
                sid, title = section.group("sid"), section.group("title")
                if sid in seen_sections:
                    continue
                seen_sections.add(sid)
                rows.append(case(
                    f"section-{sid}".lower(), "section_lookup",
                    f"What does section {sid} cover?", [f"[{sid}]"],
                    f"{path.name}:{index + 1} section heading", role,
                    {"doc_category": category},
                ))
                rows.append(case(
                    f"section-{sid}-title".lower(), "section_lookup",
                    title if title.endswith("?") else f"Tell me about {title}.",
                    [f"[{sid}]"],
                    f"{path.name}:{index + 1} section title", role,
                    {"doc_category": category},
                ))
                continue

            row = REGISTRY_ROW.match(line)
            if row:
                key = row.group("key")
                event_id = ROW_EVENT_ID.search(line[row.end() - 1:])
                if key in seen_registry or key in seen_entities or not event_id:
                    continue
                seen_registry.add(key)
                anchor = next((p for p in reversed(paths.get(index, [])) if p), None)
                if not anchor:
                    continue
                rows.append(case(
                    f"registry-{key}".lower(), "registry_keys",
                    f"Which event id and version does {key} have?", [anchor],
                    f"{path.name}:{index + 1} registry row", role,
                    {"expected_facts": [event_id.group("id")], "doc_category": category},
                ))
    return rows, classification


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--out", type=Path)
    arguments = parser.parse_args()
    rows, classification = build(arguments.corpus, arguments.project_id)

    print("INFERRED DOCUMENT CATEGORY")
    print(f"  {'document':60} {'category':16} evidence")
    for name, category, evidence in classification:
        print(f"  {name[:59]:60} {category:16} {evidence}")

    by_suite: dict[str, int] = {}
    by_role: dict[str, int] = {}
    for row in rows:
        by_suite[row["suite"]] = by_suite.get(row["suite"], 0) + 1
        by_role[row["role"]] = by_role.get(row["role"], 0) + 1
    print("\nGOLD SUITES")
    for suite, count in sorted(by_suite.items()):
        print(f"  {suite:20} {count:>5} cases")
    print(f"  {'-' * 20} {'-' * 5}")
    for role, count in sorted(by_role.items()):
        print(f"  {role:20} {count:>5} cases")
    print(f"  {'TOTAL':20} {len(rows):>5} cases")

    if arguments.out:
        arguments.out.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )
        print(f"\nwrote {arguments.out}")


if __name__ == "__main__":
    main()
