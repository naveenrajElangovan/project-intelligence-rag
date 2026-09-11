"""LiteLLM SDK routing built only from validated application settings."""

from __future__ import annotations

import os
import json
from functools import lru_cache

from app.config import Settings


# LiteLLM otherwise performs a network read for its public price table at import
# time. Model routing must never create an undeclared egress dependency.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")


def _provider_model(settings: Settings, provider: str, profile: str, task: str) -> tuple[str, dict[str, object]] | None:
    if provider == "ollama":
        if not settings.local_inference_enabled or not settings.ollama_base_url:
            return None
        name = settings.ollama_planner_model if task == "planner" else {
            "budget": settings.ollama_planner_model,
            "standard": settings.ollama_model,
            "complex": settings.ollama_model,
        }.get(profile, settings.ollama_model)
        return f"ollama/{name}", {
            "api_base": settings.ollama_base_url,
            "num_ctx": settings.ollama_context_tokens,
            "num_predict": 512 if task == "planner" else settings.ollama_max_output_tokens,
            "keep_alive": settings.ollama_keep_alive,
            # The workflow consumes schema-constrained JSON. Qwen can place the
            # whole JSON object in Ollama's hidden thinking field when thinking
            # is enabled, leaving message.content empty for LangChain's parser.
            # LiteLLM maps reasoning_effort="none" to Ollama think=false.
            "reasoning_effort": "none",
            "repeat_penalty": settings.ollama_repeat_penalty,
        }
    if provider == "openai":
        if not settings.openai_api_key:
            return None
        name = {
            "budget": settings.openai_budget_model,
            "standard": settings.openai_standard_model,
            "complex": settings.openai_complex_model,
        }.get(profile, settings.openai_standard_model)
        return f"openai/{name}", {
            "api_key": settings.openai_api_key,
        }
    if provider == "azure-openai":
        # Managed identity token refresh remains on the native Azure client. A
        # static token copied into a long-lived LiteLLM Router would expire.
        if not settings.azure_openai_endpoint or not settings.azure_openai_api_key:
            return None
        return f"azure/{settings.azure_openai_deployment}", {
            "api_base": settings.azure_openai_endpoint,
            "api_key": settings.azure_openai_api_key,
        }
    return None


def _route_spec(settings: Settings, profile: str, task: str, temperature: float):
    preferred = settings.llm_provider
    providers = (preferred,) + tuple(
        provider for provider in ("ollama", "openai", "azure-openai") if provider != preferred
    )
    model_list: list[dict[str, object]] = []
    groups: list[str] = []
    for provider in providers:
        resolved = _provider_model(settings, provider, profile, task)
        if resolved is None:
            continue
        model, params = resolved
        group = f"pi-{task}-{profile}-{provider}"
        groups.append(group)
        model_list.append({
            "model_name": group,
            "litellm_params": {
                "model": model,
                "temperature": temperature,
                "timeout": settings.llm_timeout_seconds,
                "max_retries": 0,
                **params,
            },
        })
    if not model_list:
        raise ValueError("No environment-configured model is available to LiteLLM.")
    fallbacks = [{groups[0]: groups[1:]}] if settings.litellm_fallbacks_enabled and len(groups) > 1 else []
    return tuple(model_list), tuple(groups), tuple(
        (key, tuple(value)) for item in fallbacks for key, value in item.items()
    )


@lru_cache(maxsize=24)
def _cached_router(
    model_list_json: str,
    fallback_key: tuple[tuple[str, tuple[str, ...]], ...],
    timeout: float,
    strategy: str,
):
    from litellm import Router

    model_list = json.loads(model_list_json)
    fallbacks = [{group: list(values)} for group, values in fallback_key]
    return Router(
        model_list=model_list,
        fallbacks=fallbacks,
        routing_strategy=strategy,
        num_retries=0,
        timeout=timeout,
        enable_pre_call_checks=True,
    )


def build_litellm_chat_model(
    settings: Settings,
    profile: str,
    *,
    task: str,
    temperature: float,
):
    from langchain_litellm import ChatLiteLLMRouter

    model_list, groups, fallback_key = _route_spec(settings, profile, task, temperature)
    model_list_json = json.dumps(model_list, sort_keys=True, separators=(",", ":"))
    router = _cached_router(
        model_list_json,
        fallback_key,
        settings.llm_timeout_seconds,
        settings.litellm_routing_strategy,
    )
    return ChatLiteLLMRouter(
        router=router,
        model=groups[0],
        temperature=temperature,
        request_timeout=settings.llm_timeout_seconds,
        max_retries=0,
    )
