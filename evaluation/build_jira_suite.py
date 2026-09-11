"""Build 20 bilingual pairs anchored to actual Jira evidence in a staging index."""

import argparse
import json
from pathlib import Path

from chromadb import HttpClient

from app.chroma_collections import project_collection_name, verify_project_collection


QUESTIONS = {
    "CURRENT": ("What is the current status of {key}?", "¿Cuál es el estado actual de {key}?"),
    "DESCRIPTION": ("What behavior is described in {key}?", "¿Qué comportamiento describe {key}?"),
    "ACCEPTANCE": (
        "What acceptance criteria are documented for {key}?",
        "¿Qué criterios de aceptación están documentados para {key}?",
    ),
    "COMMENT": (
        "What does comment {event} on {key} say, and when was it posted?",
        "¿Qué dice el comentario {event} de {key} y cuándo se publicó?",
    ),
    "CHANGELOG": (
        "What changed in history event {event} on {key}?",
        "¿Qué cambió en el evento histórico {event} de {key}?",
    ),
    "RELATIONSHIP": (
        "What parent or related issues are recorded for {key}?",
        "¿Qué incidencia superior o incidencias relacionadas tiene {key}?",
    ),
    "REMOTE_LINK": (
        "What external reference is linked to {key}?",
        "¿Qué referencia externa está vinculada a {key}?",
    ),
    "CUSTOM_FIELD": (
        "What additional field values are recorded for {key}?",
        "¿Qué valores de campos adicionales están registrados en {key}?",
    ),
    "GLOSSARY": ("How does {key} define {term}?", "¿Cómo define {key} el término {term}?"),
    "ATTACHMENT": (
        "What evidence does attachment {title} on {key} contain?",
        "¿Qué evidencia contiene el adjunto {title} de {key}?",
    ),
}


def application_bucket(metadata):
    """Use explicit source labels for this POS/BOT benchmark, never issue keys."""
    labels = metadata.get("labels") or []
    if isinstance(labels, str):
        try:
            labels = json.loads(labels)
        except ValueError:
            labels = []
    observed = {str(label).upper() for label in labels} if isinstance(labels, list) else set()
    applications = sorted(observed & {"POS", "BOT"})
    return "/".join(applications)


def build(records, project_id):
    if not records:
        raise ValueError("Cannot build Jira evaluation without source evidence")
    by_kind = {}
    for record in records:
        m = record["metadata"]
        kind = m.get("jira_chunk_kind") or m.get("source_type")
        by_kind.setdefault(kind, []).append(record)
    cases = []
    gaps = []
    for kind, questions in QUESTIONS.items():
        values = by_kind.get(kind, [])
        # Prefer distinct issues/events, not neighboring splits of one section.
        selected, seen = [], set()
        for record in values:
            m = record["metadata"]
            identity = (
                m.get("source_id"),
                m.get("event_id") if kind in {"COMMENT", "CHANGELOG"} else None,
            )
            if identity not in seen:
                selected.append(record)
                seen.add(identity)
        # Prefer both explicitly labelled applications when the corpus offers
        # them. Other Jira projects keep the ordinary distinct-source selection.
        pos = next(
            (record for record in selected if application_bucket(record["metadata"]) == "POS"), None
        )
        bot = next(
            (record for record in selected if application_bucket(record["metadata"]) == "BOT"), None
        )
        if pos is not None and bot is not None:
            selected = [
                pos,
                bot,
                *[record for record in selected if record is not pos and record is not bot],
            ]
        for index in range(2):
            positive = index < len(selected)
            record = selected[index] if positive else records[index % len(records)]
            m = record["metadata"]
            if not positive:
                gaps.append(
                    {"kind": kind, "slot": index, "reason": "insufficient_distinct_evidence"}
                )
            for lang, question in zip(("en", "es"), questions, strict=True):
                if positive:
                    text = question.format(
                        key=m.get("issue_key", ""),
                        event=m.get("event_id", ""),
                        term=m.get("glossary_term", ""),
                        title=m.get("title", ""),
                    )
                else:
                    # Explicit nonexistent identifier: never assert that an
                    # unsupported feature does not exist in the real project.
                    text = (
                        "What is the verified status of NONEXISTENTJIRA-999999999?"
                        if lang == "en"
                        else "¿Cuál es el estado verificado de NONEXISTENTJIRA-999999999?"
                    )
                case = {
                    "id": f"jira-{kind.lower()}-{index}-{lang}",
                    "suite": "jira_" + kind.lower(),
                    "project_id": project_id,
                    "question": text,
                    "query_language": lang,
                    "answerable": positive,
                    "derivation": "persisted Jira evidence"
                    if positive
                    else "negative identifier control",
                    "reference_answer": record["document"]
                    if positive
                    else "No supporting indexed Jira issue.",
                    "gold_match": {
                        "any_of": [
                            {
                                "all_of": [
                                    {"field": "source_id", "equals": m["source_id"]},
                                    {"field": "locator", "equals": m["locator"]},
                                ]
                            }
                        ]
                    }
                    if positive
                    else {"any_of": []},
                }
                if positive:
                    # A section may span chunks or languages. The question asks
                    # about the whole section/event, not an arbitrary first split.
                    group = [
                        item
                        for item in values
                        if item["metadata"].get("source_id") == m.get("source_id")
                        and (
                            kind not in {"COMMENT", "CHANGELOG"}
                            or item["metadata"].get("event_id") == m.get("event_id")
                        )
                    ]
                    case["reference_answer"] = "\n\n".join(item["document"] for item in group)
                    case["gold_match"]["any_of"] = [
                        {
                            "all_of": [
                                {"field": "source_id", "equals": item["metadata"]["source_id"]},
                                {"field": "locator", "equals": item["metadata"]["locator"]},
                            ]
                        }
                        for item in group
                    ]
                    case["application"] = application_bucket(m)
                cases.append(case)
    return cases, gaps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--chroma-host", default="127.0.0.1")
    parser.add_argument("--chroma-port", type=int, default=8000)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    collection = HttpClient(host=args.chroma_host, port=args.chroma_port).get_collection(
        project_collection_name(args.collection, args.project_id)
    )
    verify_project_collection(collection, args.collection, args.project_id)
    records, offset = [], 0
    while True:
        page = collection.get(
            where={
                "$and": [
                    {"project_id": args.project_id},
                    {"provider": "JIRA"},
                    {"access_policy_id": f"project:{args.project_id}"},
                ]
            },
            include=["metadatas", "documents"],
            limit=100,
            offset=offset,
        )
        records.extend(
            {"document": d, "metadata": m}
            for d, m in zip(page["documents"], page["metadatas"], strict=True)
        )
        if len(page["ids"]) < 100:
            break
        offset += len(page["ids"])
    cases, gaps = build(records, args.project_id)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases))
    args.out.with_suffix(".coverage.json").write_text(
        json.dumps(
            {
                "cases": len(cases),
                "gaps": gaps,
                "restricted_policy_evaluation": "separate_authorized_suite_required",
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
