"""Pairwise LLM-as-judge for RAG answers, with the four known biases controlled.

Pointwise scoring (what run_ragas_eval does) answers "is this answer good?".
It is poor at "did this change make things better?", because a one-to-five score
drifts between runs and hides small regressions. Pairwise comparison answers the
second question directly, but only if the well-known judge biases are handled as
mechanics rather than as polite requests in a prompt:

* Position bias -- judges favour whichever response they read first. Controlled
  by judging every pair TWICE, in both orders, and treating disagreement between
  the two passes as a tie AND as a measured bias signal. A run whose
  position_bias_rate is high has no usable win rate, and the report says so.
* Verbosity bias -- judges mistake length for thoroughness. Controlled at the
  source (both answers must come from the same answer_style, so the same
  sentence band applies) and at scoring time (a pair whose lengths differ beyond
  LENGTH_TOLERANCE is excluded from the headline number and reported separately).
  The judge is never told the lengths, so it cannot "correct" for them either.
* Self-preference and style bias -- controlled by blind labels (RESPONSE_1 /
  RESPONSE_2, never system names) and by ranking evidence faithfulness above
  fluency in the rubric.
* Rationalisation -- a verdict emitted before its reasoning is a guess with an
  explanation attached. The schema puts reasoning first, then per-criterion
  winners, then the overall verdict, so the model commits to the analysis before
  it commits to the answer.

Everything here is deterministic: temperature 0, and the display order of each
pair is derived from a hash of the case id, so the same dataset produces the
same comparison twice.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from statistics import fmean
from typing import Literal, Sequence

from pydantic import BaseModel, Field


# A pair whose answers differ in length by more than this ratio is reported but
# kept out of the headline win rate: at that point the comparison is measuring
# verbosity, not quality.
LENGTH_TOLERANCE = 1.25

Winner = Literal["RESPONSE_1", "RESPONSE_2", "TIE"]
Outcome = Literal["BASELINE", "CANDIDATE", "TIE"]


class PairwiseVerdict(BaseModel):
    """Field order is the chain of thought: analysis first, verdict last."""

    reasoning: str = Field(
        min_length=1,
        max_length=2000,
        description=(
            "Compare the two responses against the evidence, criterion by "
            "criterion, before naming any winner."
        ),
    )
    grounding_winner: Winner = Field(
        description="Which response states only what the evidence supports."
    )
    completeness_winner: Winner = Field(
        description="Which response covers more of what the question asked."
    )
    directness_winner: Winner = Field(
        description="Which response answers the question asked, without padding."
    )
    winner: Winner
    confidence: Literal["LOW", "MEDIUM", "HIGH"]


PAIRWISE_SYSTEM_PROMPT = """\
You are evaluating two candidate answers produced by a retrieval-augmented \
assistant for an enterprise project-knowledge system. You are given the user's \
question, the evidence passages the assistant retrieved, and two responses \
labelled RESPONSE_1 and RESPONSE_2.

Judge only against the evidence provided. You have no other knowledge of this \
project, and an answer that is plausible but unsupported by the evidence is \
worse than one that declines.

Apply these criteria, in this order of importance:

1. EVIDENCE FAITHFULNESS. Every claim must be supported by the evidence shown. \
An answer that invents a field, identifier, number or behaviour loses, however \
well written it is. An honest refusal beats a confident fabrication.
2. COMPLETENESS. Covers what was actually asked, including the parts that are \
inconvenient. An answer that silently omits a requested item is incomplete.
3. DIRECTNESS. Answers the question asked, rather than a related one. Restating \
the evidence without answering is not an answer.

Rules you must follow:

- IGNORE LENGTH. A longer answer is not a better answer. Do not reward detail \
that was not asked for, and do not penalise brevity that is complete.
- IGNORE STYLE, tone, formatting and confidence of phrasing. A hedged correct \
answer beats a assertive wrong one.
- IGNORE ORDER. The labels carry no meaning; RESPONSE_1 is not a default.
- ANSWER IN THE LANGUAGE OF THE QUESTION when you write your reasoning.
- TIE is a real verdict, not a failure to decide. Use it whenever the difference \
would not matter to the person who asked, or when both responses fail equally.

Write your reasoning first, comparing both responses criterion by criterion. \
Only then give the per-criterion winners and the overall verdict.\
"""

PAIRWISE_HUMAN_PROMPT = """\
QUESTION:
{question}

EVIDENCE:
{evidence}

RESPONSE_1:
{response_1}

RESPONSE_2:
{response_2}\
"""


def presentation_order(case_id: str, *, swap: bool) -> bool:
    """Return True when the baseline should be shown as RESPONSE_1.

    Derived from the case id so a rerun of the same dataset produces the same
    layout, and inverted for the second pass so every pair is seen both ways.
    """

    digest = hashlib.sha256(str(case_id).encode("utf-8")).digest()
    baseline_first = bool(digest[0] & 1)
    return not baseline_first if swap else baseline_first


def _resolve(winner: Winner, *, baseline_first: bool) -> Outcome:
    """Translate a label-based verdict back to the system it refers to."""

    if winner == "TIE":
        return "TIE"
    chose_first = winner == "RESPONSE_1"
    return "BASELINE" if chose_first == baseline_first else "CANDIDATE"


def length_ratio(first: str, second: str) -> float:
    """Word-count ratio, always >= 1.0, of the longer answer to the shorter."""

    counts = sorted((max(len(first.split()), 1), max(len(second.split()), 1)))
    return counts[1] / counts[0]


@dataclass(frozen=True)
class PairResult:
    case_id: str
    query_language: str
    outcome: Outcome
    position_bias: bool
    length_ratio: float
    length_mismatch: bool
    first_pass: Outcome
    second_pass: Outcome


def reconcile(
    case_id: str,
    *,
    query_language: str,
    baseline_answer: str,
    candidate_answer: str,
    first_pass: Winner,
    second_pass: Winner,
) -> PairResult:
    """Combine the two orderings into one verdict, and record the disagreement.

    Two passes that name different systems mean the judge followed position, not
    quality. That pair contributes a TIE to the win rate and a 1 to the bias
    rate; suppressing it silently would launder an unreliable judgement into a
    confident number.
    """

    first = _resolve(first_pass, baseline_first=presentation_order(case_id, swap=False))
    second = _resolve(second_pass, baseline_first=presentation_order(case_id, swap=True))
    disagreed = first != second and "TIE" not in (first, second)
    outcome: Outcome = "TIE" if first != second else first
    ratio = length_ratio(baseline_answer, candidate_answer)
    return PairResult(
        case_id=str(case_id),
        query_language=query_language or "und",
        outcome=outcome,
        position_bias=disagreed,
        length_ratio=round(ratio, 3),
        length_mismatch=ratio > LENGTH_TOLERANCE,
        first_pass=first,
        second_pass=second,
    )


def aggregate(results: Sequence[PairResult]) -> dict[str, float | int | str]:
    """Content-free aggregates, with the diagnostics that qualify the headline."""

    if not results:
        return {"pairs": 0}
    comparable = [r for r in results if not r.length_mismatch]
    scored = comparable or list(results)

    def _rates(rows: Sequence[PairResult], prefix: str) -> dict[str, float]:
        if not rows:
            return {}
        total = len(rows)
        return {
            f"{prefix}candidate_win_rate": sum(r.outcome == "CANDIDATE" for r in rows) / total,
            f"{prefix}baseline_win_rate": sum(r.outcome == "BASELINE" for r in rows) / total,
            f"{prefix}tie_rate": sum(r.outcome == "TIE" for r in rows) / total,
        }

    summary: dict[str, float | int | str] = {
        "pairs": len(results),
        "comparable_pairs": len(comparable),
        "length_mismatch_rate": sum(r.length_mismatch for r in results) / len(results),
        "mean_length_ratio": round(fmean(r.length_ratio for r in results), 3),
        "position_bias_rate": sum(r.position_bias for r in results) / len(results),
        **_rates(scored, ""),
    }
    for language in ("en", "es"):
        rows = [r for r in scored if r.query_language == language]
        summary.update(_rates(rows, f"{language}."))
    if "en.candidate_win_rate" in summary and "es.candidate_win_rate" in summary:
        summary["language_gap.candidate_win_rate"] = (
            float(summary["en.candidate_win_rate"])
            - float(summary["es.candidate_win_rate"])
        )
    # A judge that flips with the order has not measured quality. Say so in the
    # payload rather than leaving a reader to notice the diagnostic themselves.
    summary["verdict_reliability"] = (
        "UNRELIABLE_POSITION_BIAS"
        if float(summary["position_bias_rate"]) > 0.20
        else "OK"
    )
    return summary
