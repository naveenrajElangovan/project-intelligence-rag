import json
import re

from langchain_core.documents import Document

from app.models import ArtifactReference, RagRequest, RagResponse


def _complete_product_catalog_requested(project_id: str, question: str) -> bool:
    if project_id != "T3B-COMPANY":
        return False
    normalized = " ".join(question.casefold().split())
    return bool(
        re.search(
            r"(?:todos\s+los\s+productos|cat[aá]logo\s+completo\s+de\s+productos|"
            r"all\s+(?:the\s+)?products|complete\s+product\s+catalog)",
            normalized,
        )
    )


def _catalog_artifact(
    project_id: str, question: str, documents: list[Document]
) -> tuple[ArtifactReference, dict[str, int], str] | None:
    if not _complete_product_catalog_requested(project_id, question):
        return None
    products = {
        str(document.metadata.get("product_sku") or ""): document
        for document in documents
        if str(document.metadata.get("product_sku") or "")
    }
    if not products:
        return None
    releases = {
        str(document.metadata.get("catalog_release_id") or "")
        for document in products.values()
    }
    counts = {
        int(document.metadata.get("catalog_item_count") or 0)
        for document in products.values()
    }
    hashes = {
        str(document.metadata.get("source_content_hash") or "").lower()
        for document in products.values()
    }
    if (
        len(releases) != 1
        or "" in releases
        or len(counts) != 1
        or counts != {len(products)}
        or len(hashes) != 1
        or not re.fullmatch(r"[a-f0-9]{64}", next(iter(hashes), ""))
    ):
        return None
    release_id = next(iter(releases))
    first = next(iter(products.values()))
    raw_totals = first.metadata.get("catalog_category_totals") or {}
    if isinstance(raw_totals, str):
        try:
            raw_totals = json.loads(raw_totals)
        except ValueError:
            raw_totals = {}
    totals = (
        {str(key): int(value) for key, value in raw_totals.items()}
        if isinstance(raw_totals, dict)
        else {}
    )
    if sum(totals.values()) != len(products):
        return None
    artifact = ArtifactReference(
        type="PRODUCT_CATALOG",
        release_id=release_id,
        file_name=str(first.metadata.get("title") or f"t3b-products-{release_id}.csv"),
        format="csv",
        item_count=len(products),
        sha256=next(iter(hashes)),
        url=f"/v1/projects/{project_id}/catalog-releases/{release_id}/download",
    )
    return artifact, dict(sorted(totals.items())), release_id


def _catalog_summary(
    *, language: str, artifact: ArtifactReference, totals: dict[str, int], release_id: str
) -> str:
    effective = release_id.split(".", 1)[0]
    categories = ", ".join(f"{key}: {value}" for key, value in totals.items())
    if language == "es":
        return (
            f"Versión {release_id}, vigente desde {effective}. Total verificado: "
            f"{artifact.item_count} SKU activos. Totales por categoría: {categories}. "
            "El archivo CSV adjunto, no este resumen, es el resultado exhaustivo."
        )
    return (
        f"Release {release_id}, effective {effective}. Verified total: "
        f"{artifact.item_count} active SKUs. Category totals: {categories}. "
        "The attached CSV, not this short summary, is the exhaustive result."
    )


def catalog_response_fields(
    *,
    project_id: str,
    question: str,
    documents: list[Document],
    language: str,
    fallback_answer: str,
) -> tuple[str, list[ArtifactReference]]:
    catalog = _catalog_artifact(project_id, question, documents)
    if catalog is None:
        return fallback_answer, []
    artifact, totals, release_id = catalog
    return (
        _catalog_summary(
            language=language,
            artifact=artifact,
            totals=totals,
            release_id=release_id,
        ),
        [artifact],
    )


async def deterministic_catalog_response(
    request: RagRequest, retriever: object
) -> RagResponse | None:
    """Bypass model generation for exhaustive product-catalog requests."""

    if not _complete_product_catalog_requested(request.project_id, request.question):
        return None
    loader = getattr(retriever, "ainvoke_population", None)
    documents = await loader("product", (), ()) if loader is not None else []
    catalog = _catalog_artifact(request.project_id, request.question, documents)
    language = "es" if re.search(r"\b(?:cu[aá]les|productos|cat[aá]logo)\b", request.question.casefold()) else "en"
    if catalog is None:
        answer = (
            "No hay una versión aprobada y completa del catálogo disponible para descargar."
            if language == "es"
            else "No approved complete catalog release is available for download."
        )
        return RagResponse(
            status="INSUFFICIENT_EVIDENCE",
            answer=answer,
            confidence="NONE",
            project_id=request.project_id,
            sources=[],
            artifacts=[],
            missing_information=["approved complete product catalog release"],
            evidence_status="INSUFFICIENT",
            context_quality="INSUFFICIENT",
            coverage="PARTIAL",
            failure_reason="POPULATION_RETRIEVAL_MISS",
            resolved_intent="LIST_ALL_PRODUCTS",
        )
    artifact, totals, release_id = catalog
    return RagResponse(
        status="ANSWERED",
        answer=_catalog_summary(
            language=language, artifact=artifact, totals=totals, release_id=release_id
        ),
        confidence="HIGH",
        project_id=request.project_id,
        sources=[],
        artifacts=[artifact],
        missing_information=[],
        evidence_status="SUFFICIENT",
        context_quality="SUFFICIENT",
        context_relevance=1.0,
        context_completeness=1.0,
        coverage="COMPLETE",
        resolved_intent="LIST_ALL_PRODUCTS",
    )
