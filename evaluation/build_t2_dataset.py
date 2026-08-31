"""Build the 80-case English/Spanish acceptance-set scaffold."""

import argparse
import json
from pathlib import Path


INTENTS = (
    ("authorization", "How are project retrieval filters enforced?", "¿Cómo se aplican los filtros de recuperación del proyecto?"),
    ("queue-privacy", "What data is allowed in ingestion queue messages?", "¿Qué datos están permitidos en los mensajes de la cola de ingesta?"),
    ("docling", "How does local Docling process scanned PDFs?", "¿Cómo procesa Docling local los PDF escaneados?"),
    ("chunking", "How are table headers preserved while chunking?", "¿Cómo se conservan los encabezados de tablas al fragmentar?"),
    ("embedding", "Which field is embedded by multilingual-e5-large?", "¿Qué campo procesa multilingual-e5-large?"),
    ("translation", "Which identifiers must translation preserve?", "¿Qué identificadores debe conservar la traducción?"),
    ("reranking", "How many candidates and final chunks are reranked?", "¿Cuántos candidatos y fragmentos finales se reranquean?"),
    ("citations", "What happens when generated citations are invalid?", "¿Qué ocurre cuando las citas generadas no son válidas?"),
    ("versioning", "Which version changes force safe reprocessing?", "¿Qué cambios de versión fuerzan un reprocesamiento seguro?"),
    ("rollback", "How long is the old Chroma index retained for rollback?", "¿Cuánto tiempo se conserva el índice Chroma anterior para reversión?"),
)


def build(project_id: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source, english, spanish in INTENTS:
        variants = (
            ("en-en", english, "en", "en", True),
            ("es-es", spanish, "es", "es", True),
            ("en-es", english, "en", "es", True),
            ("es-en", spanish, "es", "en", True),
            ("identifier-en", f"For {project_id}, {english}", "en", "mixed", True),
            ("identifier-es", f"Para {project_id}, {spanish}", "es", "mixed", True),
            ("insufficient-en", f"What unrecorded owner approved {source}?", "en", "any", False),
            ("insufficient-es", f"¿Qué propietario no documentado aprobó {source}?", "es", "any", False),
        )
        for variant, question, query_language, evidence_language, answerable in variants:
            rows.append(
                {
                    "id": f"t2-{source}-{variant}",
                    "project_id": project_id,
                    "question": question,
                    "query_language": query_language,
                    "target_evidence_language": evidence_language,
                    "answerable": answerable,
                    "expected_source_labels": [source] if answerable else [],
                    "denied_project_ids": ["AAOS"],
                    "curation_status": "VERIFY_GOLD_SOURCE_IDS",
                }
            )
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    arguments = parser.parse_args()
    output = Path(__file__).with_name("t2_questions.jsonl")
    output.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False) + "\n"
            for row in build(arguments.project_id)
        ),
        encoding="utf-8",
    )
    print(f"wrote={output} cases={len(build(arguments.project_id))}")
