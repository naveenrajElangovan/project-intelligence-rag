import pytest
from app.grounding import _exact_anchors_supported


@pytest.mark.parametrize(
    "claim",
    [
        "Se publicó el 10 de septiembre de 2026 a las 10:32:31.306-0600.",
        "Posted September 10, 2026 at 10:32:31.306-0600.",
        "Posted 10 September 2026 at 10:32:31.306-0600.",
    ],
)
def test_calendar_date_translation_matches_exact_source_date(claim):
    assert _exact_anchors_supported(claim, "created: 2026-09-10T10:32:31.306-0600")


def test_different_dates_and_quantities_remain_unsupported():
    source = "created: 2026-09-10T10:32:31.306-0600"
    assert not _exact_anchors_supported("11 de septiembre de 2026", source)
    assert not _exact_anchors_supported("10 de octubre de 2026", source)
    assert not _exact_anchors_supported(
        "Se publicó el 10 de septiembre de 2026 con 99 cambios", source
    )
    assert not _exact_anchors_supported("2026-10-09", "2026-09-10")
    assert _exact_anchors_supported("Recorded in 2026", source)
