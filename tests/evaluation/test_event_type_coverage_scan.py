from evaluation.scan_event_type_coverage import coverage_summary


def test_coverage_summary_requires_exact_source_tuples_and_counts_entity_keys() -> None:
    source = (
        "enum class EventType {\n"
        '  LOGIN_POS_EVENT("POS_LOGIN", 101, "0.3"),\n'
        '  LOGOUT_POS_EVENT("POS_LOGOUT", 102, "0.2"),\n'
        "}"
    )
    documents = [
        'LOGIN_POS_EVENT("POS_LOGIN", 101, "0.3"),',
        'LOGOUT_POS_EVENT("POS_LOGOUT", 102, "9.9"),',
    ]
    metadatas = [
        {"entity_key": "POS_LOGIN_EVENT", "repository": "store-core-kotlin", "provider": "LOCAL"},
        {"entity_key": "POS", "repository": "store-core-kotlin", "provider": "LOCAL"},
    ]

    summary = coverage_summary(source, documents, metadatas)

    assert summary["expected_event_types"] == 2
    assert summary["exact_event_types"] == 1
    assert summary["coverage_rate"] == 0.5
    assert summary["missing_event_types"] == ["POS_LOGOUT"]
    assert summary["mismatched_event_types"] == {
        "POS_LOGOUT": {
            "expected": ("LOGOUT_POS_EVENT", "102", "0.2"),
            "observed": ("LOGOUT_POS_EVENT", "102", "9.9"),
        }
    }
    assert summary["entity_key_distinct_values"] == 2
    assert summary["generic_entity_key_counts"] == {"BOT": 0, "POS": 1, "IOT": 0}
