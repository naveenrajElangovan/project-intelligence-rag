import json
import asyncio

from langchain_core.documents import Document

from app.catalog_answers import (
    _catalog_artifact,
    _catalog_summary,
    deterministic_catalog_response,
)
from app.models import RagRequest


def test_all_products_uses_complete_verified_artifact_instead_of_inline_list() -> None:
    documents = [
        Document(
            page_content=f"SKU: SKU-{index}",
            metadata={
                "product_sku": f"SKU-{index}",
                "catalog_release_id": "2026-09-06.1",
                "catalog_item_count": 2,
                "catalog_category_totals": json.dumps({"FOOD": 2}),
                "source_content_hash": "a" * 64,
                "title": "t3b-products-2026-09-06.1.csv",
            },
        )
        for index in (1, 2)
    ]

    result = _catalog_artifact(
        "T3B-COMPANY", "¿Cuáles son todos los productos?", documents
    )

    assert result is not None
    artifact, totals, release_id = result
    answer = _catalog_summary(
        language="es", artifact=artifact, totals=totals, release_id=release_id
    )
    assert artifact.item_count == 2
    assert artifact.url.endswith("/2026-09-06.1/download")
    assert "archivo CSV adjunto" in answer
    assert "SKU-1" not in answer


def test_all_products_fails_closed_when_population_is_truncated() -> None:
    result = _catalog_artifact(
        "T3B-COMPANY",
        "List all products",
        [
            Document(
                page_content="SKU: SKU-1",
                metadata={
                    "product_sku": "SKU-1",
                    "catalog_release_id": "2026-09-06.1",
                    "catalog_item_count": 2,
                    "catalog_category_totals": {"FOOD": 2},
                    "source_content_hash": "a" * 64,
                },
            )
        ],
    )

    assert result is None


def test_exhaustive_request_bypasses_generation_and_returns_artifact() -> None:
    class Retriever:
        async def ainvoke_population(self, entity, labels, source_types):
            assert (entity, labels, source_types) == ("product", (), ())
            return [
                Document(
                    page_content="SKU: SKU-1",
                    metadata={
                        "product_sku": "SKU-1",
                        "catalog_release_id": "2026-09-06.1",
                        "catalog_item_count": 1,
                        "catalog_category_totals": {"FOOD": 1},
                        "source_content_hash": "a" * 64,
                        "title": "approved.csv",
                    },
                )
            ]

    response = asyncio.run(
        deterministic_catalog_response(
            RagRequest(
                projectId="T3B-COMPANY",
                collectionName="project-intelligence",
                question="List all products",
                accessPolicyIds=["project:T3B-COMPANY"],
            ),
            Retriever(),
        )
    )

    assert response is not None
    assert response.status == "ANSWERED"
    assert response.artifacts[0].item_count == 1
    assert "attached CSV" in response.answer
