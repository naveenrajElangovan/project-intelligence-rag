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
from typing import Any

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
CANONICAL_QUESTION_HEADING = re.compile(
    r"^##\s+\[(?P<qid>QUESTION-[A-Z0-9-]+)\]\s+.+$"
)
CANONICAL_QUESTION = re.compile(r"^-\s+[\u201c\"](?P<question>.+?)[\u201d\"]\s*$")
CANONICAL_ROUTE = re.compile(
    r"^(?:(?:Priority\s+)?Routes?|Rutas?(?:\s+prioritarias?)?):\s*(?P<routes>.*)$",
    re.IGNORECASE,
)
CANONICAL_SECTION_ID = re.compile(r"\[([A-Z][A-Z0-9-]+)\]")


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
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_REGISTRY = Path(__file__).with_name("suites.json")
_PARSER_KINDS = {"canonical_question_index", "qa_pairs", "section_titles"}


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
                    f"Which event id and version does {key} have?",
                    [key, key.removesuffix("_EVENT")],
                    f"{path.name}:{index + 1} registry row", role,
                    {"expected_facts": [event_id.group("id")], "doc_category": category},
                ))
    return rows, classification


def parse_store_canonical_index(
    path: Path,
    language: str,
    *,
    project_id: str = "T2.0-STORE",
    suite_id: str = "store_canonical_questions",
    department: str = "",
) -> list[dict]:
    """Turn one reviewed store question index into source-bound gold cases.

    The question index is the authority for both the user wording and its
    destination sections. Page ids are intentionally not used as gold: the
    bracketed section ids survive Confluence moves and re-chunking.
    """

    if language not in {"en", "es"}:
        raise ValueError(f"Unsupported canonical index language: {language!r}")
    lines = path.read_text(encoding="utf-8").splitlines()
    groups: list[tuple[str, list[str], list[str], int]] = []
    question_id: str | None = None
    questions: list[str] = []
    route_ids: list[str] = []
    heading_line = 0
    collecting_questions = False
    collecting_routes = False

    def finish_group() -> None:
        nonlocal questions, route_ids
        if question_id is None or not questions:
            questions = []
            route_ids = []
            return
        if not route_ids:
            raise ValueError(
                f"{path}:{heading_line} {question_id} has questions but no routed section ids"
            )
        groups.append((question_id, questions, route_ids, heading_line))
        questions = []
        route_ids = []

    for line_number, line in enumerate(lines, 1):
        heading = CANONICAL_QUESTION_HEADING.match(line)
        if heading:
            finish_group()
            question_id = heading.group("qid")
            heading_line = line_number
            collecting_questions = False
            collecting_routes = False
            continue
        if line.strip() in {"Equivalent questions:", "Preguntas equivalentes:"}:
            collecting_questions = True
            continue
        route = CANONICAL_ROUTE.match(line)
        if route and question_id is not None:
            collecting_questions = False
            collecting_routes = True
            route_ids.extend(CANONICAL_SECTION_ID.findall(route.group("routes")))
            route_ids = list(dict.fromkeys(route_ids))
            continue
        if collecting_routes:
            if not line.strip():
                if route_ids:
                    collecting_routes = False
            else:
                route_ids.extend(CANONICAL_SECTION_ID.findall(line))
                route_ids = list(dict.fromkeys(route_ids))
            continue
        if collecting_questions:
            question = CANONICAL_QUESTION.match(line)
            if question:
                questions.append(question.group("question").strip())
    finish_group()

    rows: list[dict] = []
    sequence = 0
    for group_id, variants, sections, line_number in groups:
        for question in variants:
            sequence += 1
            answerable = group_id != "QUESTION-OUT-OF-SCOPE"
            row = {
                "id": f"store-{language}-{sequence:03d}",
                "suite": suite_id,
                "role": "answer_evidence",
                "project_id": project_id,
                "department": department,
                "question": question,
                "query_language": language,
                "target_evidence_language": language,
                "answerable": answerable,
                "gold_match": {
                    "any_of": [
                        {"field": "structure_path", "contains": f"[{section}]"}
                        for section in sections
                    ]
                },
                "canonical_group": group_id,
                "gold_section_ids": sections,
                "derivation": f"{path.name}:{line_number} {group_id} routes",
                "evaluation_lane": "generation" if not answerable else "retrieval",
            }
            if not answerable:
                row["expected_refusal_reason"] = "INSUFFICIENT_EVIDENCE"
            rows.append(row)
    return rows


def build_store_canonical_suite(english: Path, spanish: Path) -> list[dict]:
    rows = parse_store_canonical_index(english, "en") + parse_store_canonical_index(
        spanish, "es"
    )
    counts = {
        language: sum(row["query_language"] == language for row in rows)
        for language in ("en", "es")
    }
    if counts != {"en": 184, "es": 184}:
        raise ValueError(f"Store canonical indexes must contain 184 questions each: {counts}")
    return rows


def load_registry(path: Path = _DEFAULT_REGISTRY) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    suites = payload.get("suites")
    if not isinstance(suites, list):
        raise ValueError(f"{path} must contain a suites array")
    identifiers: set[str] = set()
    for suite in suites:
        identifier = str(suite.get("id") or "")
        kind = str((suite.get("source") or {}).get("kind") or "")
        if not identifier or identifier in identifiers:
            raise ValueError(f"Invalid or duplicate suite id: {identifier!r}")
        if kind not in _PARSER_KINDS:
            raise ValueError(f"Suite {identifier} has unsupported parser kind {kind!r}")
        identifiers.add(identifier)
    return suites


def _resolve_patterns(patterns: list[str], language: str | None = None) -> list[Path]:
    resolved: list[Path] = []
    for pattern in patterns:
        rendered = pattern.format(lang=language or "")
        matches = sorted(_REPOSITORY_ROOT.glob(rendered))
        if not matches:
            raise ValueError(f"Suite source pattern matched no files: {rendered}")
        resolved.extend(matches)
    return list(dict.fromkeys(resolved))


def _qa_pair_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else list(payload.get("cases", []))


def _section_title_rows(
    path: Path, *, suite_id: str, project_id: str, language: str, department: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        heading = ANY_HEADING.match(line)
        if not heading or len(heading.group("hashes")) < 2:
            continue
        title = heading.group("text").strip()
        rows.append(
            {
                "id": f"{suite_id}-{language}-{path.stem}-{line_number}",
                "suite": suite_id,
                "project_id": project_id,
                "department": department,
                "role": "answer_evidence",
                "question": title if title.endswith("?") else f"Tell me about {title}.",
                "query_language": language,
                "target_evidence_language": language,
                "answerable": True,
                "gold_match": {"any_of": [{"field": "structure_path", "contains": title}]},
                "derivation": f"{path.name}:{line_number} section title",
            }
        )
    return rows


def build_registered_suites(
    *,
    project_id: str,
    suite_ids: set[str] | None = None,
    department: str | None = None,
    registry_path: Path = _DEFAULT_REGISTRY,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build all configured suites for a project; onboarding needs no parser edit."""

    selected = [
        suite
        for suite in load_registry(registry_path)
        if suite.get("project_id") == project_id
        and (not suite_ids or suite.get("id") in suite_ids)
        and (
            department is None
            or department in (suite.get("departments") or [])
            or (not department and not (suite.get("departments") or []))
        )
    ]
    if not selected:
        raise ValueError(f"No registered suites for project={project_id!r}, suite={suite_ids}, department={department!r}")
    cases: list[dict[str, Any]] = []
    for suite in selected:
        source = suite["source"]
        kind = source["kind"]
        departments = suite.get("departments") or [""]
        if department is not None:
            departments = [department]
        for configured_department in departments:
            for language in source.get("languages") or ["und"]:
                paths = _resolve_patterns(source.get("paths") or [], language)
                for path in paths:
                    if kind == "canonical_question_index":
                        parsed = parse_store_canonical_index(
                            path,
                            language,
                            project_id=project_id,
                            suite_id=suite["id"],
                            department=configured_department,
                        )
                    elif kind == "qa_pairs":
                        parsed = _qa_pair_rows(path)
                    else:
                        parsed = _section_title_rows(
                            path,
                            suite_id=suite["id"],
                            project_id=project_id,
                            language=language,
                            department=configured_department,
                        )
                    for row in parsed:
                        if row.get("project_id", project_id) != project_id:
                            continue
                        row = {**row, "suite": suite["id"], "project_id": project_id}
                        row.setdefault("department", configured_department)
                        row.setdefault("gold_granularity", (suite.get("gold") or {}).get("granularity", "chunk"))
                        row.setdefault("suite_gates", suite.get("gates") or {})
                        cases.append(row)
    deduplicated = {str(row["id"]): row for row in cases}
    return list(deduplicated.values()), selected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--registry", type=Path, default=_DEFAULT_REGISTRY)
    parser.add_argument("--suite", action="append", dest="suite_ids")
    parser.add_argument("--department")
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--store-canonical-root",
        type=Path,
        help="Build the 368-case bilingual T2.0-STORE suite from this documentation root.",
    )
    parser.add_argument(
        "--store-out",
        type=Path,
        default=Path(__file__).with_name("store_gold_suites.jsonl"),
    )
    arguments = parser.parse_args()
    if arguments.project_id and not arguments.corpus and not arguments.store_canonical_root:
        rows, _definitions = build_registered_suites(
            project_id=arguments.project_id,
            suite_ids=set(arguments.suite_ids or []),
            department=arguments.department,
            registry_path=arguments.registry,
        )
        output = arguments.out or Path(__file__).with_name(f"{arguments.project_id}.gold.jsonl")
        output.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
        print(f"wrote {len(rows)} registered cases to {output}")
        return
    if arguments.store_canonical_root:
        store_rows = build_store_canonical_suite(
            arguments.store_canonical_root
            / "en/topics/10_CANONICAL_QUESTION_INDEX.md",
            arguments.store_canonical_root
            / "es/topics/10_INDICE_DE_PREGUNTAS_CANONICAS.md",
        )
        arguments.store_out.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in store_rows) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {len(store_rows)} store cases to {arguments.store_out}")
        if not arguments.corpus:
            return
    if arguments.corpus is None or not arguments.project_id:
        parser.error("--corpus and --project-id are required unless only --store-canonical-root is used")
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
