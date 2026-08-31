import json

from app.vocabulary import CorpusVocabulary, VOCABULARY_RECORD_KIND


def test_vocabulary_accepts_document_json_and_normalizes_values() -> None:
    vocabulary = CorpusVocabulary.from_record(
        {"record_kind": VOCABULARY_RECORD_KIND},
        json.dumps(
            {
                "record_kind": VOCABULARY_RECORD_KIND,
                "entities": ["Retail", "Warehouse"],
                "doc_categories": ["Feature-Page", "Workflow"],
                "providers": ["confluence", "github"],
                "source_types": ["page", "code"],
                "code_extensions": ["swift", ".tf"],
                "languages": ["EN", "es"],
            }
        ),
    )

    assert vocabulary.entities == ("retail", "warehouse")
    assert vocabulary.doc_categories == ("feature-page", "workflow")
    assert vocabulary.providers == ("CONFLUENCE", "GITHUB")
    assert vocabulary.source_types == ("PAGE", "CODE")
    assert vocabulary.code_extensions == (".swift", ".tf")
    assert vocabulary.languages == ("en", "es")


def test_non_vocabulary_record_never_enables_specialized_behavior() -> None:
    assert CorpusVocabulary.from_record(
        {"record_kind": "content", "entities": ["retail"]}
    ) == CorpusVocabulary()
