from evaluation.compare_nonjira_application import compare


def test_unverified_sources_do_not_count_as_final_evidence():
    source = {
        "type": "PAGE",
        "title": "Doc",
        "reference": "p",
        "url": "https://example.test/p",
        "locator": "s",
    }
    records = [
        {
            "metadata": {
                "source_id": "page:1",
                "source_type": "PAGE",
                "title": "Doc",
                "reference": "p",
                "source_url": source["url"],
                "locator": "s",
            }
        }
    ]
    case = {
        "id": "one",
        "query_language": "en",
        "question": "requirements?",
        "answerable": True,
        "gold_match": {"any_of": [{"all_of": [{"field": "source_id", "equals": "page:1"}]}]},
    }
    baseline = {
        "status": "EXECUTION_COMPLETE_REVIEW_PENDING",
        "cases": [{"id": "one", "response": {"sources": [source], "evidenceStatus": "SUFFICIENT"}}],
    }
    staged = {
        "status": "EXECUTION_COMPLETE_REVIEW_PENDING",
        "cases": [
            {"id": "one", "response": {"sources": [source], "evidenceStatus": "INSUFFICIENT"}}
        ],
    }
    result = compare([case], records, baseline, staged)
    assert result["maximum_regression_percentage_points"] == 100
    assert result["passed"] is False


def test_public_unverified_source_cards_do_not_turn_an_explicit_refusal_into_an_answer():
    from app.llm import refusal_answer

    case = {
        "id": "one",
        "query_language": "en",
        "question": "Who approved an unrecorded phantom?",
        "answerable": False,
        "gold_match": {"any_of": []},
    }
    result = {
        "status": "EXECUTION_COMPLETE_REVIEW_PENDING",
        "cases": [
            {
                "id": "one",
                "response": {
                    "confidence": "NONE",
                    "evidenceStatus": "UNVERIFIED",
                    "answer": refusal_answer("UNVERIFIED_EVIDENCE", "en"),
                    "sources": [{"type": "PAGE", "title": "Unverified candidate"}],
                },
            }
        ],
    }
    measured = compare([case], [], result, result)
    assert measured["cases_detail"][0]["baseline"]["verified_abstention"] is True
    result["cases"][0]["response"]["answer"] = "The unrecorded owner is the cashier."
    measured = compare([case], [], result, result)
    assert measured["cases_detail"][0]["baseline"]["verified_abstention"] is False
