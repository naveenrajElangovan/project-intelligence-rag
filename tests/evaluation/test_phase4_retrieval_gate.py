from app.chroma_collections import configured_collection_name
from evaluation.run_phase4_retrieval_gate import registry_entries


def test_gate_defaults_to_the_primary_serving_collection() -> None:
    assert configured_collection_name(None, "active-project-route") == "active-project-route"
    assert (
        configured_collection_name("operator-override", "active-project-route")
        == "operator-override"
    )


def test_registry_cases_are_derived_without_provider_enums() -> None:
    entries = registry_entries(
        [
            "Constant | Wire name | Id | Ver | Publisher\n"
            "LOGIN_POS_EVENT | POS_LOGIN | 101 | 0.3 | POS\n"
            "FUTURE_EVENT | FUTURE_WIRE | 999 | 2,1 | FUTURE"
        ]
    )

    assert entries == {
        "POS_LOGIN": ("LOGIN_POS_EVENT", "101", "0.3"),
        "FUTURE_WIRE": ("FUTURE_EVENT", "999", "2.1"),
    }


def test_registry_cases_are_derived_from_authoritative_kotlin_enum() -> None:
    entries = registry_entries(
        [
            "enum class EventType {\n"
            '  LOGIN_POS_EVENT("POS_LOGIN", 101, "0.3"),\n'
            '  BOT_CONFIRM_EXPENSES("BOT_CONFIRM_EXPENSES", 225, "0,1"),\n'
            '  CEDIS_ITEMS_TRANSFER_ORDER_EVENT("CEDIS_ITEMS_TRANSFER_ORDER", 501, "0.2");\n'
            "}"
        ]
    )

    assert entries == {
        "POS_LOGIN": ("LOGIN_POS_EVENT", "101", "0.3"),
        "BOT_CONFIRM_EXPENSES": ("BOT_CONFIRM_EXPENSES", "225", "0.1"),
        "CEDIS_ITEMS_TRANSFER_ORDER": (
            "CEDIS_ITEMS_TRANSFER_ORDER_EVENT",
            "501",
            "0.2",
        ),
    }
