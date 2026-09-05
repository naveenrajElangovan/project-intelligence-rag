from __future__ import annotations

import asyncio
import re

from langchain_core.documents import Document

from app.config import Settings
from app.accelerator import accelerator_scores
from app.llm import ClaimRejection, GroundedAnswer, GroundingVerdict, TokenUsage
from app.reranking import (
    normalized_relevance_score,
    predict_local_scores,
    sanitize_evidence,
    scoring_evidence,
)
from app.table_evidence import contains_table, linearize_table_row, literal_table_row_evidence
from app.workflow_support.answer_structure import (
    AnswerLineKind,
    material_claims as structured_material_claims,
)


class LocalCitationGroundingVerifier:
    """Verify each cited claim against only the evidence it explicitly cites."""

    def __init__(self, settings: Settings) -> None:
        self._model_ref = settings.local_models_path or settings.local_rerank_model
        self._device = settings.local_rerank_device
        self._revision = settings.local_rerank_revision
        self._threshold = settings.grounding_score_threshold
        self._cross_language_threshold = settings.grounding_cross_language_score_threshold
        self._table_threshold = settings.grounding_table_evidence_score_threshold
        self._linearize_table_evidence = settings.linearize_table_evidence
        # Populated by verify(); read by the workflow for telemetry.
        self.last_rejections: list[ClaimRejection] = []
        # Accepted claim scores, so the threshold can be chosen from the
        # observed distribution instead of guessed. Content-free: numbers only.
        self.last_accepted_scores: list[float] = []
        self.model_name = settings.local_rerank_model
        self._batch_size = settings.local_rerank_batch_size
        self._max_length = settings.local_rerank_max_length
        self._accelerator_url = settings.local_accelerator_url
        self._accelerator_api_key = settings.internal_api_key
        self._accelerator_timeout_seconds = settings.local_accelerator_timeout_seconds
        self._accelerator_attempts = settings.local_accelerator_retry_attempts
        self.last_usage = TokenUsage()
        self._pair_score_cache: dict[tuple[str, str], float] = {}

    def _predict_scores(
        self, pairs: list[tuple[str, str]], batch_size: int
    ) -> list[float]:
        if self._accelerator_url:
            # Batched by the client. A long answer produces more claim/evidence
            # pairs than one request may carry, and the rejection would fail the
            # whole verification rather than verify fewer claims.
            scores = accelerator_scores(
                self._accelerator_url,
                pairs,
                api_key=self._accelerator_api_key,
                timeout_seconds=self._accelerator_timeout_seconds,
                max_length=self._max_length,
                attempts=self._accelerator_attempts,
            )
            if len(scores) != len(pairs):
                raise RuntimeError(
                    "Local accelerator returned invalid grounding scores."
                )
            return scores
        return [
            float(value)
            for value in predict_local_scores(
                self._model_ref,
                device=self._device,
                revision=self._revision,
                pairs=pairs,
                batch_size=batch_size,
                max_length=self._max_length,
            )
        ]

    def _scored(self, page_content: str) -> str:
        """The exact text the cross-encoder will see for this evidence."""

        return scoring_evidence(
            page_content, linearize_tables_enabled=self._linearize_table_evidence
        )

    def _threshold_for(self, *, cross_language: bool, table_evidence: bool) -> float:
        """Pick the bar this comparison has to clear.

        Cross-language comes first: comparing across languages is the harder
        problem of the two, so its (lower) bar wins when both apply. The table bar
        is opt-in and stays unset by default -- linearising the table is meant to
        make the normal bar reachable, and a lower bar is a weaker check, not a
        fix for evidence the model genuinely cannot confirm.
        """

        if cross_language:
            return self._cross_language_threshold
        if table_evidence and self._table_threshold is not None:
            return self._table_threshold
        return self._threshold

    async def _ensure_scores(
        self, pairs: list[tuple[str, str]], *, batch_size: int | None = None
    ) -> None:
        missing = list(
            dict.fromkeys(pair for pair in pairs if pair not in self._pair_score_cache)
        )
        if not missing:
            return
        raw_scores = await asyncio.to_thread(
            self._predict_scores,
            missing,
            batch_size or self._batch_size,
        )
        for pair, raw_score in zip(missing, raw_scores, strict=True):
            self._pair_score_cache[pair] = normalized_relevance_score(float(raw_score))

    def _verification_score_pairs(
        self,
        structured_claim: object,
        claim: str,
        documents: list[Document],
        cited: list[int],
        literal_evidence: str,
    ) -> tuple[tuple[str, str], ...]:
        """One scoring pair per cited source, best score wins.

        These used to be concatenated into a single pair. The cross-encoder
        truncates a pair to `local_rerank_max_length`, and truncation drops the
        tail, so a claim whose support happened to sit in its last cited source
        scored as if that source were absent and the sentence was removed from
        the answer. Scoring each source on its own keeps every citation inside
        the model's window regardless of how many were cited.
        """

        kind = getattr(structured_claim, "kind", None)
        table_header = str(getattr(structured_claim, "table_header", ""))
        score_claim = (
            linearize_table_row(table_header, claim)
            if kind is AnswerLineKind.TABLE_ROW
            else claim
        )
        exact_row_evidence = (
            literal_table_row_evidence(table_header, claim, literal_evidence)
            if kind is AnswerLineKind.TABLE_ROW
            else None
        )
        if exact_row_evidence:
            return ((score_claim, exact_row_evidence),)
        return tuple(
            (score_claim, self._scored(documents[number - 1].page_content))
            for number in cited
        )

    def _best_score(self, pairs: tuple[tuple[str, str], ...]) -> float:
        """The strongest support among a claim's cited sources."""

        return max(self._pair_score_cache[pair] for pair in pairs)

    async def attach_missing_citations(
        self,
        documents: list[Document],
        answer: GroundedAnswer,
    ) -> GroundedAnswer:
        """Attach only citations independently supported by the local cross-encoder."""

        updated = answer.answer
        self._pair_score_cache.clear()
        # Build every (claim, evidence) pair first and score them in one batch.
        # Scoring per claim inside a loop serialised one cross-encoder forward pass
        # per sentence behind the shared inference lock, which dominated latency on
        # a multi-sentence answer.
        pending: list[tuple[str, list[tuple[int, tuple[tuple[str, str], ...]]]]] = []
        verification_pairs: list[tuple[str, str]] = []
        for structured_claim in structured_material_claims(answer.answer):
            sentence = structured_claim.text
            source_numbers = [
                int(value) for value in re.findall(r"\[SOURCE (\d+)\]", sentence)
            ]
            claim = re.sub(r"\s*\[SOURCE \d+\]", "", sentence).strip()
            if structured_claim.kind is AnswerLineKind.LIST_ITEM:
                claim = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", claim)
            if source_numbers:
                cited = list(dict.fromkeys(source_numbers))
                if any(number < 1 or number > len(documents) for number in cited):
                    continue
                literal_evidence = "\n".join(
                    sanitize_evidence(documents[number - 1].page_content)
                    for number in cited
                )
                if _exact_anchors_supported(
                    claim, literal_evidence
                ) and _negation_supported(claim, literal_evidence):
                    verification_pairs.extend(
                        self._verification_score_pairs(
                            structured_claim,
                            claim,
                            documents,
                            cited,
                            literal_evidence,
                        )
                    )
                continue
            eligible: list[tuple[int, tuple[tuple[str, str], ...]]] = []
            for index, document in enumerate(documents, start=1):
                literal_evidence = sanitize_evidence(document.page_content)
                if not _exact_anchors_supported(
                    claim, literal_evidence
                ) or not _negation_supported(claim, literal_evidence):
                    continue
                eligible.append(
                    (
                        index,
                        self._verification_score_pairs(
                            structured_claim,
                            claim,
                            documents,
                            [index],
                            literal_evidence,
                        ),
                    )
                )
            if eligible:
                pending.append((sentence, eligible))
        if pending:
            flat_pairs = [
                pair
                for _sentence, eligible in pending
                for _index, group in eligible
                for pair in group
            ]
            # A citation must be attached under the same bar verify() will apply,
            # or the answer gains a marker that the very next stage rejects.
            flat_thresholds = [
                self._threshold_for(
                    cross_language=False,
                    table_evidence=contains_table(sanitize_evidence(documents[index - 1].page_content)),
                )
                for _sentence, eligible in pending
                for index, _group in eligible
            ]
            await self._ensure_scores(flat_pairs + verification_pairs)
            for sentence, eligible in pending:
                thresholds = flat_thresholds[: len(eligible)]
                del flat_thresholds[: len(eligible)]
                supported = [
                    (self._best_score(group), index)
                    for (index, group), threshold in zip(
                        eligible, thresholds, strict=True
                    )
                    if self._best_score(group) >= threshold
                ]
                if not supported:
                    continue
                _score, source_number = max(supported)
                cited = _append_marker(sentence.strip(), source_number)
                updated = updated.replace(sentence, cited, 1)
        elif verification_pairs:
            await self._ensure_scores(verification_pairs)
        citations = list(
            dict.fromkeys(int(value) for value in re.findall(r"\[SOURCE (\d+)\]", updated))
        )
        return answer.model_copy(update={"answer": updated, "citations": citations})

    async def verify(
        self,
        question: str,
        documents: list[Document],
        answer: GroundedAnswer,
        *,
        answer_language: str = "",
    ) -> GroundingVerdict:
        del question
        claims = structured_material_claims(answer.answer)
        invalid_claims: list[str] = []
        rejections: list[ClaimRejection] = []
        accepted_scores: list[float] = []
        score_groups: list[tuple[tuple[str, str], ...]] = []
        score_claims: list[str] = []
        score_thresholds: list[float] = []
        score_indexes: list[int] = []
        score_table_evidence: list[bool] = []

        for position, structured_claim in enumerate(claims, start=1):
            sentence = structured_claim.text
            source_numbers = [
                int(value) for value in re.findall(r"\[SOURCE (\d+)\]", sentence)
            ]
            if not source_numbers or any(
                number < 1 or number > len(documents) for number in source_numbers
            ):
                invalid_claims.append(sentence)
                rejections.append(
                    ClaimRejection(
                        claim_index=position, reason="MISSING_OR_INVALID_CITATION"
                    )
                )
                continue
            claim = re.sub(r"\s*\[SOURCE \d+\]", "", sentence).strip()
            if structured_claim.kind is AnswerLineKind.LIST_ITEM:
                claim = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", claim)
            cited = list(dict.fromkeys(source_numbers))
            # Anchor and negation checks read the literal evidence: they look for
            # an exact substring, and linearisation would move the characters.
            literal_evidence = "\n".join(
                sanitize_evidence(documents[number - 1].page_content) for number in cited
            )
            table_evidence = contains_table(literal_evidence)
            if not _exact_anchors_supported(claim, literal_evidence):
                # Two failures wear one reason code here, and they need opposite
                # responses. If the anchor is absent from every authorized
                # document the model invented it and the claim must go. If it is
                # present in another retrieved document, the fact is real and the
                # citation points at the wrong source -- a misattribution, where
                # deleting the claim loses supported content. Naming which one
                # occurred is what makes the difference measurable.
                all_evidence = "\n".join(
                    sanitize_evidence(document.page_content) for document in documents
                )
                anchored_elsewhere = _exact_anchors_supported(claim, all_evidence)
                invalid_claims.append(sentence)
                rejections.append(
                    ClaimRejection(
                        claim_index=position,
                        reason=(
                            "ANCHOR_CITED_TO_WRONG_SOURCE"
                            if anchored_elsewhere
                            else "NUMERIC_OR_IDENTIFIER_ANCHOR_ABSENT"
                        ),
                        table_evidence=table_evidence,
                    )
                )
                continue
            if not _negation_supported(claim, literal_evidence):
                invalid_claims.append(sentence)
                rejections.append(
                    ClaimRejection(
                        claim_index=position,
                        reason="NEGATION_UNSUPPORTED",
                        table_evidence=table_evidence,
                    )
                )
                continue
            score_groups.append(
                self._verification_score_pairs(
                    structured_claim,
                    claim,
                    documents,
                    cited,
                    literal_evidence,
                )
            )
            score_claims.append(sentence)
            score_indexes.append(position)
            score_table_evidence.append(table_evidence)
            evidence_languages = {
                str(documents[number - 1].metadata.get("language") or "").casefold()
                for number in cited
            } - {"", "und", "mixed"}
            cross_language = (
                answer_language in {"en", "es"}
                and bool(evidence_languages)
                and answer_language not in evidence_languages
            )
            score_thresholds.append(
                self._threshold_for(
                    cross_language=cross_language, table_evidence=table_evidence
                )
            )

        # _ensure_scores already skips pairs attach_missing_citations cached,
        # so passing the full set costs nothing and keeps the bookkeeping in one
        # place.
        await self._ensure_scores(
            [pair for group in score_groups for pair in group]
        )
        resolved_scores = [self._best_score(group) for group in score_groups]
        for sentence, score, threshold, position, table_evidence in zip(
            score_claims,
            resolved_scores,
            score_thresholds,
            score_indexes,
            score_table_evidence,
            strict=True,
        ):
            if score < threshold:
                invalid_claims.append(sentence)
                rejections.append(
                    ClaimRejection(
                        claim_index=position,
                        reason="SCORE_BELOW_THRESHOLD",
                        score=round(score, 4),
                        threshold=threshold,
                        table_evidence=table_evidence,
                    )
                )
            else:
                accepted_scores.append(round(score, 4))

        self.last_rejections = rejections
        self.last_accepted_scores = accepted_scores
        # Cache lifetime is one attach->verify pipeline. Keeping scores beyond a
        # completed verdict would make a later answer reuse stale model output.
        self._pair_score_cache.clear()
        if not claims or invalid_claims:
            return GroundingVerdict(
                supported=False,
                unsupported_claims=invalid_claims or ["No material cited claim was produced."],
                reason_code="UNSUPPORTED_CLAIM",
            )
        return GroundingVerdict(
            supported=True,
            unsupported_claims=[],
            reason_code="SUPPORTED",
        )


def _material_claims(answer: str) -> list[str]:
    return [claim.text for claim in structured_material_claims(answer)]


def _exact_anchors_supported(claim: str, evidence: str) -> bool:
    claim_numbers = _numeric_anchors(claim)
    evidence_numbers = _numeric_anchors(evidence)
    if not claim_numbers.issubset(evidence_numbers):
        return False
    claim_identifiers = set(re.findall(r"`([^`]+)`", claim))
    return all(identifier in evidence for identifier in claim_identifiers)


def _numeric_anchors(value: str) -> set[str]:
    return {
        _canonical_number(number)
        for number in re.findall(r"(?<![\w])\d+(?:[.,]\d+)*(?![\w])", value)
    }


def _canonical_number(value: str) -> str:
    # Qwen may render an evidence integer such as 12356 as 12,356 (English) or
    # 12.356 (Spanish). Treat only conventional groups of three as thousands
    # separators. Ordinary decimals such as 3.14 remain decimals and therefore
    # cannot match an integer 314.
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", value):
        return re.sub(r"[.,]", "", value)
    return value.replace(",", ".")


def _negation_supported(claim: str, evidence: str) -> bool:
    pattern = r"\b(?:no|not|never|none|without|zero|0)\b"
    return not re.search(pattern, claim, flags=re.IGNORECASE) or bool(
        re.search(pattern, evidence, flags=re.IGNORECASE)
    )


def _append_marker(sentence: str, source_number: int) -> str:
    match = re.search(r"([.!?])\s*$", sentence)
    if match:
        return sentence[: match.start()] + f" [SOURCE {source_number}]" + match.group(1)
    return sentence + f" [SOURCE {source_number}]"
