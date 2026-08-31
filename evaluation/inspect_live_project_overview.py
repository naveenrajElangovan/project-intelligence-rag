"""Inspect the live project-overview evidence, draft, and grounding outcome."""

from __future__ import annotations

import asyncio
import argparse
import re

from app.config import Settings
from app.models import RagRequest
from app.workflow import AuthorizedRagWorkflow
from app.reranking import normalized_relevance_score, predict_local_scores


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--question")
    arguments = parser.parse_args()
    settings = Settings()
    request = RagRequest(
        projectId=arguments.project_id,
        collectionName="project-intelligence",
        textField="chunk_text",
        embeddingField="embedding_text",
        embeddingModel="multilingual-e5-large",
        schemaVersion="3",
        question=arguments.question or f"what do you know about {arguments.project_id} project",
        accessPolicyIds=[f"project:{arguments.project_id}"],
        modelProfile="budget",
    )
    workflow = AuthorizedRagWorkflow(settings, request)
    state = {"request": request}
    for stage in (
        workflow._plan_queries,
        workflow._retrieve,
        workflow._feature_affinity,
        workflow._rerank,
        workflow._validate_evidence_completeness,
        workflow._generate,
        workflow._validate_citations,
        workflow._validate_completeness,
    ):
        state.update(await stage(state))
    print("EVIDENCE")
    for index, document in enumerate(state["documents"], start=1):
        print(
            f"{index}: provider={document.metadata.get('provider')} "
            f"type={document.metadata.get('source_type')} title={document.metadata.get('title')} "
            f"ordinal={document.metadata.get('chunk_ordinal')}"
        )
    print("DRAFT")
    print(state["generated"].answer)
    print("CITATIONS", state["generated"].citations)
    claims = re.split(r"(?<=[.!?])\s+|\n+", state["generated"].answer.strip())
    print("CLAIM_SCORES")
    for claim in claims:
        source_numbers = [int(value) for value in re.findall(r"\[SOURCE (\d+)\]", claim)]
        if not source_numbers:
            continue
        claim_text = re.sub(r"\s*\[SOURCE \d+\]", "", claim).strip()
        evidence = "\n".join(
            state["documents"][number - 1].page_content
            for number in dict.fromkeys(source_numbers)
        )
        scores = await asyncio.to_thread(
            predict_local_scores,
            settings.local_models_path or settings.local_rerank_model,
            device=settings.local_rerank_device,
            revision=settings.local_rerank_revision,
            pairs=[(claim_text, evidence)],
        )
        print(f"{normalized_relevance_score(float(scores[0])):.4f}\t{claim}")
    negative_controls = (
        "BOT procesa nóminas y solicitudes de vacaciones de empleados.",
        "BOT administra campañas de marketing y publicidad digital.",
        "BOT diagnostica pacientes y recomienda tratamientos médicos.",
    )
    all_evidence = "\n".join(document.page_content for document in state["documents"])
    negative_scores = await asyncio.to_thread(
        predict_local_scores,
        settings.local_models_path or settings.local_rerank_model,
        device=settings.local_rerank_device,
        revision=settings.local_rerank_revision,
        pairs=[(claim, all_evidence) for claim in negative_controls],
    )
    print("NEGATIVE_CONTROL_SCORES")
    for claim, score in zip(negative_controls, negative_scores, strict=True):
        print(f"{normalized_relevance_score(float(score)):.4f}\t{claim}")
    verdict = await workflow._grounding_verifier.verify(
        request.question, state["documents"], state["generated"]
    )
    print("GROUNDING", verdict.model_dump())


if __name__ == "__main__":
    asyncio.run(main())
