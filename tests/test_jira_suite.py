from evaluation.build_jira_suite import build


def test_jira_suite_uses_real_locators_and_reports_missing_categories():
    records = [
        {
            "document": "Current status: In Review",
            "metadata": {
                "jira_chunk_kind": "CURRENT",
                "issue_key": "T0-12",
                "source_id": "jira:cloud:issue:1",
                "locator": "current:1",
            },
        }
    ]
    cases, gaps = build(records, "APP")
    assert len(cases) == 40
    assert len([c for c in cases if c["query_language"] == "en"]) == 20
    positive = [c for c in cases if c["answerable"]]
    assert len(positive) == 2
    assert positive[0]["gold_match"]["any_of"][0]["all_of"][1]["equals"] == "current:1"
    assert gaps
    assert all("NONEXISTENTJIRA" in c["question"] for c in cases if not c["answerable"])


def test_jira_suite_prefers_explicit_application_diversity_without_key_assumptions():
    records = [
        {
            "document": "Current status: In Review",
            "metadata": {
                "jira_chunk_kind": "CURRENT",
                "issue_key": key,
                "source_id": "jira:cloud:issue:" + key,
                "locator": "current:1",
                "labels": labels,
            },
        }
        for key, labels in (("OTHER-1", '["pos"]'), ("OTHER-2", '["pos"]'), ("OTHER-3", '["bot"]'))
    ]
    cases, _ = build(records, "OTHER_APP")
    positive = [case for case in cases if case["answerable"]]
    assert [case["application"] for case in positive] == ["POS", "POS", "BOT", "BOT"]
    assert all("OTHER-3" in case["question"] for case in positive[2:])
