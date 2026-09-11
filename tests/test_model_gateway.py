from app.config import Settings
from app.model_gateway import _route_spec, build_litellm_chat_model


def _settings(**updates):
    values = {
        "environment": "development",
        "llm_provider": "ollama",
        "ollama_base_url": "http://ollama:11434",
        "ollama_model": "answer-model",
        "ollama_planner_model": "planner-model",
        "local_inference_enabled": True,
        "openai_api_key": "",
        "azure_openai_endpoint": "",
        "azure_openai_api_key": "",
        **updates,
    }
    return Settings(_env_file=None, **values)


def test_litellm_routes_profiles_to_models_from_settings() -> None:
    model_list, groups, fallbacks = _route_spec(
        _settings(), "standard", "answer", 0.0
    )

    assert groups == ("pi-answer-standard-ollama",)
    assert fallbacks == ()
    assert model_list[0]["litellm_params"]["model"] == "ollama/answer-model"
    assert model_list[0]["litellm_params"]["api_base"] == "http://ollama:11434"
    assert "presence_penalty" not in model_list[0]["litellm_params"]
    assert model_list[0]["litellm_params"]["reasoning_effort"] == "none"


def test_litellm_uses_other_configured_models_only_as_failure_fallbacks() -> None:
    model_list, groups, fallbacks = _route_spec(
        _settings(openai_api_key="secret", openai_standard_model="gpt-standard"),
        "standard",
        "answer",
        0.0,
    )

    assert groups == ("pi-answer-standard-ollama", "pi-answer-standard-openai")
    assert model_list[1]["litellm_params"]["model"] == "openai/gpt-standard"
    assert fallbacks == ((groups[0], (groups[1],)),)


def test_langchain_model_is_backed_by_litellm_router() -> None:
    model = build_litellm_chat_model(
        _settings(), "budget", task="planner", temperature=0.0
    )

    assert model._llm_type == "LiteLLMRouter"
    assert model.model == "pi-planner-budget-ollama"
