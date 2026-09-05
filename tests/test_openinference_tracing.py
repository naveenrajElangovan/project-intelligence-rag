from app.config import Settings
from app.openinference_tracing import configure_openinference


def test_openinference_is_opt_in_by_default() -> None:
    settings = Settings(environment="development", openinference_enabled=False)
    assert configure_openinference(settings) is None
