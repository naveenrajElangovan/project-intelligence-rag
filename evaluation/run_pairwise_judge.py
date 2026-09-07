"""Compare two RAG configurations answer-by-answer with a local judge.

    python -m evaluation.run_pairwise_judge \
        --baseline .quality-runs/<run>/ragas-input.jsonl \
        --candidate .quality-runs/<run>/ragas-input.jsonl \
        --output .quality-runs/<run>/pairwise.json

Both inputs are the content-bearing generation-lane files produced by
run_retrieval_eval, joined on case_id. Every pair is judged twice, in both
orders. Only aggregates leave this process; questions, answers and evidence stay
in the local files.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
from typing import Any

from evaluation.pairwise_judge import (
    PAIRWISE_HUMAN_PROMPT,
    PAIRWISE_SYSTEM_PROMPT,
    PairwiseVerdict,
    aggregate,
    presentation_order,
    reconcile,
)


def _load(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        key = str(row.get("case_id") or row.get("id") or "")
        if not key:
            raise ValueError("every row needs a case_id")
        if key in rows:
            raise ValueError(f"duplicate case_id: {key}")
        rows[key] = row
    return rows


def _evidence(row: dict[str, Any], limit: int) -> str:
    contexts = [str(value) for value in row.get("retrieved_contexts", [])]
    return "\n\n---\n\n".join(contexts)[:limit] or "(no evidence retrieved)"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=os.getenv("PI_RAG_RAGAS_MODEL", ""))
    parser.add_argument(
        "--base-url", default=os.getenv("PI_RAG_RAGAS_BASE_URL", "http://127.0.0.1:11434/v1")
    )
    parser.add_argument("--api-key", default=os.getenv("PI_RAG_RAGAS_API_KEY", "ollama"))
    parser.add_argument("--evidence-characters", type=int, default=6000)
    parser.add_argument("--timeout", type=int, default=300)
    arguments = parser.parse_args()

    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI
    from app.config import get_settings

    model = arguments.model or get_settings().ollama_model
    if model.endswith(":latest"):
        raise SystemExit(
            "Refusing a floating judge tag: pin the model so runs stay comparable."
        )

    baseline_rows = _load(arguments.baseline)
    candidate_rows = _load(arguments.candidate)
    shared = sorted(set(baseline_rows) & set(candidate_rows))
    if not shared:
        raise SystemExit("The two files share no case_id.")

    judge = ChatOpenAI(
        model=model,
        base_url=arguments.base_url,
        api_key=arguments.api_key,
        temperature=0,
        timeout=arguments.timeout,
        extra_body={"think": False},
    )
    chain = (
        ChatPromptTemplate.from_messages(
            [("system", PAIRWISE_SYSTEM_PROMPT), ("human", PAIRWISE_HUMAN_PROMPT)]
        )
        | judge.with_structured_output(PairwiseVerdict)
    )

    results = []
    for position, case_id in enumerate(shared, 1):
        baseline, candidate = baseline_rows[case_id], candidate_rows[case_id]
        baseline_answer = str(baseline.get("response") or "")
        candidate_answer = str(candidate.get("response") or "")
        # Evidence comes from the baseline run: both systems answered the same
        # question, and showing two evidence sets would make the judge compare
        # retrieval and generation at once.
        evidence = _evidence(baseline, arguments.evidence_characters)
        passes = []
        for swap in (False, True):
            baseline_first = presentation_order(case_id, swap=swap)
            first, second = (
                (baseline_answer, candidate_answer)
                if baseline_first
                else (candidate_answer, baseline_answer)
            )
            verdict = await chain.ainvoke(
                {
                    "question": str(baseline.get("user_input") or ""),
                    "evidence": evidence,
                    "response_1": first,
                    "response_2": second,
                }
            )
            passes.append(verdict.winner)
        results.append(
            reconcile(
                case_id,
                query_language=str(baseline.get("query_language") or "und"),
                baseline_answer=baseline_answer,
                candidate_answer=candidate_answer,
                first_pass=passes[0],
                second_pass=passes[1],
            )
        )
        print(f"case={position}/{len(shared)} id={case_id}", flush=True)

    payload = {
        "section": "pairwise",
        "judge_model": model,
        "pairs": [asdict(result) for result in results],
        "scores": aggregate(results),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["scores"], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
