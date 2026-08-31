import asyncio
from pathlib import Path
import runpy


LABS = Path(__file__).parents[1] / "labs"


def test_lab_3_routes_to_grounded_evidence() -> None:
    module = runpy.run_path(str(LABS / "lab03_langgraph.py"))
    assert asyncio.run(module["run"]())["route"] == "grounded"


def test_lab_4_shows_immutable_authorization_filter() -> None:
    module = runpy.run_path(str(LABS / "lab04_chroma_security.py"))
    result = asyncio.run(module["run"]())
    assert result["search"]["where"]["$and"] == [
        {"project_id": {"$eq": "DEMO"}},
        {"access_policy_id": {"$eq": "project:DEMO"}},
        {"canonical_chunk_id": {"$ne": "__vocabulary__"}},
    ]


def test_lab_5_rejects_out_of_range_citation() -> None:
    module = runpy.run_path(str(LABS / "lab05_rag_security.py"))
    result = module["run"]()
    assert result["valid_citation"] is True
    assert result["invalid_citation"] is False
    assert "\x00" not in result["sanitized_evidence"]
