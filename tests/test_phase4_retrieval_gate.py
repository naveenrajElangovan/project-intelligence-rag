from evaluation.run_phase4_retrieval_gate import registry_entries


def test_registry_cases_are_derived_without_provider_enums() -> None:
    entries = registry_entries([
        "Constant | Wire name | Id | Ver | Publisher\n"
        "LOGIN_POS_EVENT | POS_LOGIN | 101 | 0.3 | POS\n"
        "FUTURE_EVENT | FUTURE_WIRE | 999 | 2,1 | FUTURE"
    ])

    assert entries == {
        "POS_LOGIN": ("LOGIN_POS_EVENT", "101", "0.3"),
        "FUTURE_WIRE": ("FUTURE_EVENT", "999", "2.1"),
    }
