import pytest

from app.workflow_support.query_analysis import _source_route_intent


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        ("What is the status of the payment configuration ticket?", "DELIVERY"),
        ("Which bugs block the checkout implementation?", "DELIVERY"),
        ("List the open Jira issues for authentication", "DELIVERY"),
        ("What priority does the release ticket have?", "DELIVERY"),
        ("¿Cuál es el estado del ticket de configuración?", "DELIVERY"),
        ("¿Qué errores bloquean la implementación?", "DELIVERY"),
        ("Lista las incidencias de Jira abiertas", "DELIVERY"),
        ("¿Qué prioridad tiene el bloqueo?", "DELIVERY"),
        ("How is the invoice total implemented?", "IMPLEMENTATION"),
        ("Which class validates the password?", "IMPLEMENTATION"),
        ("Show the repository path for this function", "IMPLEMENTATION"),
        ("What configuration file defines the dependency?", "IMPLEMENTATION"),
        ("¿Cómo está implementado el cálculo?", "IMPLEMENTATION"),
        ("¿Qué clase valida la contraseña?", "IMPLEMENTATION"),
        ("¿Cuál ruta contiene esta función?", "IMPLEMENTATION"),
        ("¿Qué archivo configura la dependencia?", "IMPLEMENTATION"),
        ("Compare the documented flow with the implementation", "CROSS_SOURCE"),
        ("Does the policy match the source code?", "CROSS_SOURCE"),
        ("What differs between documentation and code?", "CROSS_SOURCE"),
        ("Align the architecture description with the repository", "CROSS_SOURCE"),
        ("Compara el flujo documentado con la implementación", "CROSS_SOURCE"),
        ("¿Coincide la política con el código?", "CROSS_SOURCE"),
        ("¿Qué diferencia hay entre documentación y código?", "CROSS_SOURCE"),
        ("Compara la arquitectura contra el repositorio", "CROSS_SOURCE"),
        ("What does the checkout feature do?", "CODE_ASSISTED"),
        ("Where is the refund policy documented?", "CODE_ASSISTED"),
        ("Explain the order workflow", "CODE_ASSISTED"),
        ("What are the supported payment methods?", "CODE_ASSISTED"),
        ("¿Qué hace la función de pago?", "IMPLEMENTATION"),
        ("¿Dónde está documentada la política?", "CODE_ASSISTED"),
        ("Explica el flujo de pedidos", "CODE_ASSISTED"),
        ("¿Cuáles son los métodos de pago admitidos?", "CODE_ASSISTED"),
        ("What blocks BOT from closing the store day?", "CODE_ASSISTED"),
        (
            "BOT no permite finalizar el día. ¿Cuáles son exactamente los tres bloqueos?",
            "CODE_ASSISTED",
        ),
        ("Show tickets about source code", "DELIVERY"),
        ("Show issues about configuration", "DELIVERY"),
        ("Show bugs in implementation", "DELIVERY"),
        ("Lista tickets sobre código", "DELIVERY"),
        ("Where is this documented?", "CODE_ASSISTED"),
        ("¿Dónde está documentado?", "CODE_ASSISTED"),
        ("Compare behavior and tests", "CROSS_SOURCE"),
        ("Compara el comportamiento y las pruebas", "CROSS_SOURCE"),
    ],
)
def test_source_routing_matrix(question: str, intent: str) -> None:
    assert _source_route_intent(question, ("PAGE", "CODE", "ISSUE")) == intent


def test_cross_source_is_not_required_when_code_is_unavailable() -> None:
    assert (
        _source_route_intent(
            "Compare the documented refund policy with the implementation",
            ("PAGE",),
        )
        == "IMPLEMENTATION"
    )
