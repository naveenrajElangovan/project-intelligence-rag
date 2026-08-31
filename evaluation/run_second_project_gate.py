"""Create, verify, and remove a tiny corpus with unrelated project vocabulary."""

from __future__ import annotations

import argparse
import asyncio
import json

from chromadb import HttpClient

from app.chroma_collections import project_collection_name
from app.config import Settings
from app.embedding import build_embedder
from app.retrieval import ChromaAccessRetriever
from app.workflow_support.query_analysis import (
    _entity_overview_entity,
    _feature_inventory_entity,
    _inventory_documents,
    _source_route_intent,
)


async def run(arguments: argparse.Namespace) -> dict[str, object]:
    settings = Settings(
        chroma_host=arguments.chroma_host,
        chroma_port=arguments.chroma_port,
        chroma_collection=arguments.collection,
    )
    client = HttpClient(host=arguments.chroma_host, port=arguments.chroma_port)
    physical_name = project_collection_name(arguments.collection, arguments.project_id)
    collection = client.create_collection(
        physical_name,
        metadata={
            "project_id": arguments.project_id,
            "logical_collection": arguments.collection,
            "hnsw:space": "cosine",
        },
    )
    try:
        records = (
            ("atlas-routing", "Routing handbook", "Atlas plans delivery routes and dispatches vehicles.", "PAGE", "atlas", "feature-page"),
            ("atlas-telemetry", "Fleet observations", "Atlas records route telemetry for operators.", "PAGE", "atlas", "feature-page"),
            ("nova-ledger", "Settlement ledger", "Nova reconciles settlement ledger entries.", "PAGE", "nova", "workflow"),
            ("nova-engine", "engine.go", "package ledger implements settlement reconciliation", "CODE", "nova", "narrative"),
        )
        vocabulary_id = "__vocabulary__"
        vocabulary = {
            "record_kind": vocabulary_id,
            "project_id": arguments.project_id,
            "entities": ["atlas", "nova"],
            "doc_categories": ["feature-page", "workflow", "narrative"],
            "providers": ["CONFLUENCE", "GITHUB"],
            "source_types": ["PAGE", "CODE"],
            "code_extensions": [".go", ".rs"],
            "languages": ["en"],
        }
        documents = [record[2] for record in records] + [json.dumps(vocabulary)]
        ids = [record[0] for record in records] + [vocabulary_id]
        metadatas = [
            {
                "canonical_chunk_id": chunk_id,
                "project_id": arguments.project_id,
                "access_policy_id": f"project:{arguments.project_id}",
                "schema_version": settings.supported_schema_versions[0],
                "embedding_model": settings.supported_embedding_models[0],
                "source_type": source_type,
                "provider": "GITHUB" if source_type == "CODE" else "CONFLUENCE",
                "title": title,
                "source_id": f"fixture:{chunk_id}",
                "structure_path": json.dumps([title]),
                "entity": entity,
                "doc_category": category,
            }
            for chunk_id, title, _content, source_type, entity, category in records
        ]
        metadatas.append(
            {
                "canonical_chunk_id": vocabulary_id,
                "project_id": arguments.project_id,
                "access_policy_id": f"project:{arguments.project_id}",
                "schema_version": settings.supported_schema_versions[0],
                "embedding_model": settings.supported_embedding_models[0],
                "source_type": "SYSTEM",
                "provider": "LOCAL",
                "title": "Project vocabulary",
                "source_id": "fixture:vocabulary",
                "record_kind": vocabulary_id,
                **{key: json.dumps(value) for key, value in vocabulary.items() if isinstance(value, list)},
            }
        )
        embedder = build_embedder(settings)
        collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embedder.embed_queries(documents),
        )
        retriever = ChromaAccessRetriever.create(
            chroma_host=arguments.chroma_host,
            chroma_port=arguments.chroma_port,
            collection_name=arguments.collection,
            text_field="chunk_text",
            project_id=arguments.project_id,
            access_policy_ids=(f"project:{arguments.project_id}",),
            top_k=4,
            score_threshold=0.0,
            required_schema_version=settings.supported_schema_versions[0],
            required_embedding_model=settings.supported_embedding_models[0],
            embedder=embedder,
        )
        loaded = retriever.corpus_vocabulary()
        overview = await retriever.ainvoke("Tell me about Atlas")
        inventory = _inventory_documents(overview, "atlas")
        routes = {
            question: _source_route_intent(question, loaded.source_types)
            for question in (
                "What does route planning do?",
                "Which class implements settlement?",
                "Compare the handbook with the implementation",
                "Which bugs block settlement?",
            )
        }
        result = {
            "project_id": arguments.project_id,
            "entity_vocabulary_size": len(loaded.entities),
            "entity_overview": _entity_overview_entity(
                "Tell me about Atlas", loaded.entities
            ),
            "feature_inventory": _feature_inventory_entity(
                "List all Atlas features", loaded.entities
            ),
            "retrieved": len(overview),
            "inventory": len(inventory),
            "routes": sorted(set(routes.values())),
            "entity_capability": "enabled" if loaded.entities else "disabled",
        }
        if (
            result["entity_overview"] != "atlas"
            or result["feature_inventory"] != "atlas"
            or not overview
            or not inventory
            or len(set(routes.values())) != 4
            or result["entity_capability"] != "enabled"
        ):
            raise RuntimeError(f"Second-project gate failed: {result}")
        return result
    finally:
        client.delete_collection(physical_name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--chroma-host", default="127.0.0.1")
    parser.add_argument("--chroma-port", type=int, default=8000)
    parser.add_argument("--collection", default="project-intelligence-second-gate")
    result = asyncio.run(run(parser.parse_args()))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
