"""Answer length was hard-coded inside every style instruction, which made
"answer more fully" impossible without editing prompts."""

import pytest
from langchain_core.documents import Document

from app.config import Settings
from app.llm import (
    _ANSWER_SKELETON,
    _LIST_RULE,
    _paragraph_range,
    _sentence_range,
    _table_instruction,
    answer_sentence_floor,
)


def _settings(detail: str) -> Settings:
    return Settings.model_construct(answer_detail=detail)


@pytest.mark.parametrize("band", ["short", "medium", "long"])
def test_detailed_allows_more_than_standard(band):
    assert _sentence_range(_settings("detailed"), band) != _sentence_range(
        _settings("standard"), band
    )


def test_bands_stay_ordered_within_a_detail_level():
    settings = _settings("standard")
    assert (
        _sentence_range(settings, "short"),
        _sentence_range(settings, "medium"),
        _sentence_range(settings, "long"),
    ) == ("two to four", "three to six", "four to six")


def test_detailed_widens_the_paragraph_allowance():
    assert _paragraph_range(_settings("detailed")) == "three to five short paragraphs"
    assert _paragraph_range(_settings("brief")) == "one or two short paragraphs"


def test_unknown_detail_falls_back_to_standard_rather_than_raising():
    # Defence in depth: the configuration validator rejects an unknown value, so
    # reaching here means the object was constructed some other way. Degrading to
    # standard keeps generation working instead of failing the request.
    assert _sentence_range(_settings("enormous"), "long") == _sentence_range(
        _settings("standard"), "long"
    )


def test_list_rule_asks_for_one_item_per_bullet_with_its_own_citation():
    assert "one item per bullet" in _LIST_RULE
    assert "citation" in _LIST_RULE


@pytest.mark.parametrize("detail", ["brief", "standard", "detailed"])
def test_configuration_accepts_every_documented_band(detail):
    assert Settings.model_construct(answer_detail=detail).answer_detail == detail


def test_configuration_rejects_an_undocumented_band():
    with pytest.raises(ValueError, match="PI_RAG_ANSWER_DETAIL"):
        Settings(answer_detail="verbose")


def test_answer_contract_starts_directly_and_separates_missing_information():
    assert "begin with one or two sentences" in _ANSWER_SKELETON
    assert "missing_information" in _ANSWER_SKELETON


def test_table_instruction_activates_only_for_material_tabular_evidence():
    table = Document(
        page_content="| Field | Type |\n|---|---|\n| a | string |\n| b | integer |\n| c | bool |",
        metadata={"doc_category": "entity-contract"},
    )
    prose = Document(page_content="A short narrative.", metadata={"doc_category": "narrative"})
    assert "Field | Type | Required | Description | Source" in _table_instruction([table, prose])
    assert _table_instruction([prose, prose]) == ""


def test_detailed_post_prune_floor_uses_the_active_style_band():
    settings = _settings("detailed")
    assert answer_sentence_floor(settings, "concise") == 4
    assert answer_sentence_floor(settings, "entity_overview") == 6
    assert answer_sentence_floor(settings, "project_overview") == 8
