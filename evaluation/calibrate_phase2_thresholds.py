"""Calibrate Phase-2 rerank and grounding thresholds with the pinned local model."""

from __future__ import annotations

import json

from app.config import Settings
from app.reranking import normalized_relevance_score, predict_local_scores


REGISTRY = '''LOGIN_POS_EVENT("POS_LOGIN", 101, "0.3"); POS_CLOSE_SHIFT_EVENT("POS_CLOSE_SHIFT", 104, "0.4"); POS_CLOSE_SHIFT_REQUEST_EVENT("POS_CLOSE_SHIFT_REQUEST", 116, "0.1")'''
CLOSE_SHIFT = """POS_CLOSE_SHIFT CloseShiftEvent fields: event_type, event_id, version_number, user, userConfirmedAmountCents, event_datetime, operation_date, folio, store_id, pos_id, shift_id, shift_date, request_id, shift_summary, authorized_by."""
LOGIN = """POS_LOGIN LoginEvent fields: event_type, event_id, version_number, user, event_datetime, operation_date, store_id, pos_id, status, session_id, message."""
UNRELATED = "Printer settings configure paper width, margins, and receipt density."

RERANK_CASES = (
    (True, "POS_CLOSE_SHIFT_EVENT what does this event require?", CLOSE_SHIFT),
    (True, "POS_CLOSE_SHIFT_EVENT what does this event require?", REGISTRY),
    (False, "POS_CLOSE_SHIFT_EVENT what does this event require?", LOGIN),
    (False, "POS_CLOSE_SHIFT_EVENT what does this event require?", UNRELATED),
    (True, "LOGIN_POS_EVENT what does this event contain?", LOGIN),
    (True, "LOGIN_POS_EVENT what does this event contain?", REGISTRY),
    (False, "LOGIN_POS_EVENT what does this event contain?", CLOSE_SHIFT),
    (False, "LOGIN_POS_EVENT what does this event contain?", UNRELATED),
)

GROUNDING_CASES = (
    (True, "POS_CLOSE_SHIFT_EVENT has wire name POS_CLOSE_SHIFT, id 104, and version 0.4.", REGISTRY),
    (True, "LOGIN_POS_EVENT has wire name POS_LOGIN, id 101, and version 0.3.", REGISTRY),
    (True, "POS_CLOSE_SHIFT_EVENT carries user, confirmed amount, folio, shift summary, and authorization.", CLOSE_SHIFT),
    (True, "El evento POS_CLOSE_SHIFT incluye usuario, monto confirmado, folio, resumen de turno y autorización.", CLOSE_SHIFT),
    (True, "POS_LOGIN carries user, operation date, store, POS, status, session id, and message.", LOGIN),
    (False, "POS_CLOSE_SHIFT_EVENT has id 999 and version 8.7.", REGISTRY),
    (False, "POS_LOGIN contains a shift summary and an authorized-by field.", LOGIN),
    (False, "The lunar deployment policy requires three satellite approvals.", CLOSE_SHIFT),
)


def _score(settings: Settings, cases) -> list[tuple[bool, float]]:
    raw = predict_local_scores(
        settings.local_models_path or settings.local_rerank_model,
        device=settings.local_rerank_device,
        revision=settings.local_rerank_revision,
        pairs=[(query, evidence) for _expected, query, evidence in cases],
        batch_size=len(cases),
    )
    return [
        (expected, normalized_relevance_score(float(value)))
        for (expected, _query, _evidence), value in zip(cases, raw, strict=True)
    ]


def _summary(scored: list[tuple[bool, float]]) -> dict[str, float]:
    positive = [score for expected, score in scored if expected]
    negative = [score for expected, score in scored if not expected]
    return {"positive_min": min(positive), "negative_max": max(negative)}


def main() -> None:
    settings = Settings()
    result = {
        "rerank": _summary(_score(settings, RERANK_CASES)),
        "grounding": _summary(_score(settings, GROUNDING_CASES)),
        "configured": {
            "rerank": settings.rerank_score_threshold,
            "grounding": settings.grounding_score_threshold,
            "cross_language": settings.grounding_cross_language_score_threshold,
            "table": settings.grounding_table_evidence_score_threshold,
        },
    }
    if result["rerank"]["negative_max"] >= settings.rerank_score_threshold:
        raise SystemExit("Rerank threshold admits a measured negative case.")
    if result["rerank"]["positive_min"] < settings.rerank_score_threshold:
        raise SystemExit("Rerank threshold rejects a measured positive case.")
    if result["grounding"]["negative_max"] >= settings.grounding_cross_language_score_threshold:
        raise SystemExit("Grounding threshold admits a measured negative case.")
    if result["grounding"]["positive_min"] < settings.grounding_score_threshold:
        raise SystemExit("Grounding threshold rejects a measured positive case.")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
