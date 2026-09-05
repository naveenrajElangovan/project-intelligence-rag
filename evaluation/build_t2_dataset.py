"""Build the source-bound 80-case English/Spanish acceptance set."""

import argparse
import json
from pathlib import Path


EVENT_EN = "Tiendas 3B BOT/POS Event and Integration Contract"
EVENT_ES = "Tiendas 3B BOT/POS Event and Integration Contract Spanish"
FEATURES_EN = "BOT-RAG-01_BOT_Product_Features_and_User_Capabilities"
FEATURES_ES = "BOT-RAG-01_BOT_Product_Features_and_User_Capabilities_Spanish"
WORKFLOWS_EN = "BOT-RAG-02_BOT_End_to_End_Business_Workflows_and_Rules"
WORKFLOWS_ES = "BOT-RAG-02_BOT_End_to_End_Business_Workflows_and_Rules_Spanish"
ARCHITECTURE_EN = "BOT-RAG-03_BOT_System_Architecture_Modules_and_Runtime"
ARCHITECTURE_ES = "BOT-RAG-03_BOT_System_Architecture_Modules_and_Runtime_Spanish"
DATA_EN = "BOT-RAG-04_BOT_Data_Persistence_Events_Integrations_and_Security"
DATA_ES = "BOT-RAG-04_BOT_Data_Persistence_Events_Integrations_and_Security_Spanish"


# Every positive is tied to a section that exists in both live English and
# Spanish sources. Titles are exact so cross-language rows cannot accidentally
# resolve against the same-language mirror.
INTENTS = (
    ("start-shift", "What does POS_START_SHIFT require?", "¿Qué requiere POS_START_SHIFT?", "POS_START_SHIFT", EVENT_EN, EVENT_ES),
    ("payment", "What does POS_PAYMENT_TRANSACTION represent?", "¿Qué representa POS_PAYMENT_TRANSACTION?", "POS_PAYMENT_TRANSACTION", EVENT_EN, EVENT_ES),
    ("cash-custody", "How does BOT handle cash custody?", "¿Cómo gestiona BOT la custodia de efectivo?", "BOTFEAT-030", FEATURES_EN, FEATURES_ES),
    ("inventory", "How does BOT count inventory?", "¿Cómo realiza BOT el recuento de inventario?", "BOTFEAT-060", FEATURES_EN, FEATURES_ES),
    ("store-day", "How is the BOT store day opened?", "¿Cómo se abre el día de tienda en BOT?", "BOTFLOW-020", WORKFLOWS_EN, WORKFLOWS_ES),
    ("settlement", "How does the POS settlement workflow operate?", "¿Cómo funciona el flujo de liquidación del POS?", "BOTFLOW-040", WORKFLOWS_EN, WORKFLOWS_ES),
    ("platforms", "How are platforms separated in the BOT architecture?", "¿Cómo se separan las plataformas en la arquitectura BOT?", "BOTARCH-070", ARCHITECTURE_EN, ARCHITECTURE_ES),
    ("libraries", "Which shared Tiendas 3B libraries does BOT use?", "¿Qué bibliotecas compartidas de Tiendas 3B utiliza BOT?", "BOTARCH-080", ARCHITECTURE_EN, ARCHITECTURE_ES),
    ("catalogs", "How are catalogs persisted in BOT?", "¿Cómo se almacenan los catálogos en BOT?", "BOTDATA-040", DATA_EN, DATA_ES),
    ("security", "How does BOT handle authentication and authorization security?", "¿Cómo gestiona BOT la seguridad de autenticación y autorización?", "BOTDATA-060", DATA_EN, DATA_ES),
)


def _gold_match(title: str, anchor: str) -> dict[str, object]:
    return {
        "any_of": [
            {
                "all_of": [
                    {"field": "title", "equals": title},
                    {"field": "structure_path", "contains": anchor},
                ]
            }
        ]
    }


def build(project_id: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source, english, spanish, anchor, english_title, spanish_title in INTENTS:
        variants = (
            ("en-en", english, "en", "en", english_title, True),
            ("es-es", spanish, "es", "es", spanish_title, True),
            ("en-es", english, "en", "es", spanish_title, True),
            ("es-en", spanish, "es", "en", english_title, True),
            ("project-en", f"For project {project_id}, {english}", "en", "en", english_title, True),
            ("project-es", f"Para el proyecto {project_id}, {spanish}", "es", "es", spanish_title, True),
            ("insufficient-en", f"What unrecorded owner approved phantom-{source}?", "en", "any", "", False),
            ("insufficient-es", f"¿Qué propietario no documentado aprobó phantom-{source}?", "es", "any", "", False),
        )
        for variant, question, query_language, evidence_language, title, answerable in variants:
            row: dict[str, object] = {
                "id": f"t2-{source}-{variant}",
                "suite": "bilingual_curated",
                "role": "answer_evidence",
                "project_id": project_id,
                "question": question,
                "query_language": query_language,
                "target_evidence_language": evidence_language,
                "answerable": answerable,
                "denied_project_ids": ["AAOS"],
                "curation_status": "CURATED",
            }
            if answerable:
                row["gold_match"] = _gold_match(title, anchor)
            else:
                row["expected_refusal_reason"] = "INSUFFICIENT_EVIDENCE"
                row["evaluation_lane"] = "generation"
            rows.append(row)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).with_name("bilingual_gold_suites.jsonl"),
    )
    arguments = parser.parse_args()
    output = arguments.out
    output.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False) + "\n"
            for row in build(arguments.project_id)
        ),
        encoding="utf-8",
    )
    print(f"wrote={output} cases={len(build(arguments.project_id))}")
