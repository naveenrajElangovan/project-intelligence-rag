from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str
    allowed_hosts: str = "localhost,127.0.0.1,rag,testserver"
    force_https: bool = False
    docs_enabled: bool = True
    max_request_body_bytes: int = 262_144
    rate_limit_per_minute: int = 120
    internal_api_key: str = ""
    chroma_host: str = "chroma"
    chroma_port: int = 8000
    chroma_collection: str = "project-intelligence"
    supported_embedding_models: tuple[str, ...] = ("multilingual-e5-large",)
    supported_schema_versions: tuple[str, ...] = ("3",)
    llm_provider: str = "ollama"
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen3.5:latest"
    # Defaults to the generator on purpose. Ollama holds one model resident per
    # `keep_alive`; two distinct models on a machine that cannot fit both are
    # unloaded and reloaded on every request, which costs far more than the
    # planner call saves. Point this at a smaller model only after confirming
    # both stay resident under `ollama ps`.
    ollama_planner_model: str = "qwen3.5:latest"
    # Qwen3.5 reports a native context of 262,144 tokens and uses hybrid attention,
    # so most layers keep no KV cache and long context is comparatively cheap. The
    # launcher raises this to a tier chosen from installed memory.
    ollama_context_tokens: int = 32_768
    ollama_max_output_tokens: int = 768
    # A presence penalty discourages the token repetition that verbatim citation
    # needs, so it is pinned off here rather than inherited from a Modelfile.
    ollama_presence_penalty: float = 0.0
    ollama_repeat_penalty: float = 1.0
    # Whole-prompt budgeting. Evidence receives whatever the fixed parts leave.
    prompt_overhead_reserve_tokens: int = 2_048
    max_conversation_history_tokens: int = 2_000
    max_semantic_context_tokens: int = 1_000
    ollama_keep_alive: str = "5m"
    ollama_reasoning_enabled: bool = False
    local_inference_enabled: bool = True
    warm_local_models_on_startup: bool = True
    local_max_concurrency: int = 1
    max_inflight_requests: int = 4
    load_shed_wait_seconds: float = 0.05
    openai_api_key: str = ""
    openai_budget_model: str = "gpt-5-nano"
    openai_standard_model: str = "gpt-5-mini"
    openai_complex_model: str = "gpt-5"
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = ""
    azure_openai_use_managed_identity: bool = False
    retrieval_top_k: int = 25
    retrieval_score_threshold: float = 0.0
    adaptive_query_enabled: bool = True
    query_expansion_enabled: bool = True
    hyde_enabled: bool = False
    max_query_variants: int = 3
    max_entity_expansions: int = 5
    max_retrieval_attempts: int = 2
    dependency_retry_attempts: int = 3
    dependency_timeout_seconds: float = 20.0
    lexical_fallback_enabled: bool = True
    lexical_fallback_max_records: int = 5000
    lexical_fallback_cache_ttl_seconds: int = 300
    warm_lexical_corpus_on_startup: bool = True
    vocabulary_cache_ttl_seconds: int = 300
    llm_retry_attempts: int = 2
    llm_timeout_seconds: float = 45.0
    llm_stream_idle_timeout_seconds: float = 20.0
    llm_stream_total_timeout_seconds: float = 180.0
    request_timeout_seconds: float = 240.0
    rank_fusion_k: int = 60
    lexical_fusion_weight: float = 1.25
    dense_fusion_weight: float = 1.0
    exact_term_boost: float = 0.15
    # Removes the candidate-volume advantage of large sources after fusion.
    # Zero is the neutral value used while calibrating a corpus snapshot.
    source_volume_discount_strength: float = 0.0
    neighbor_expansion_enabled: bool = True
    max_neighbors_per_anchor: int = 1
    embedding_dimensions: int = 1024
    local_embedding_model: str = "intfloat/multilingual-e5-large"
    local_embedding_revision: str = ""
    local_embedding_device: str = "mps"
    local_embedding_path: str = ""
    local_embedding_batch_size: int = 16
    warm_local_embedder_on_startup: bool = True
    local_rerank_model: str = "BAAI/bge-reranker-v2-m3"
    local_rerank_revision: str = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
    local_rerank_device: str = "mps"
    # A 50-candidate pool at batch 8 is seven sequential MPS round trips.
    local_rerank_batch_size: int = 32
    local_models_path: str = ""
    # Raised off 2. Two chunks was a consequence of the 12k context ceiling, not a
    # retrieval finding. Re-measure with evaluation/run_live_acceptance.py after any
    # further change here.
    # How much prose an answer is allowed to be. The style instructions used to
    # hard-code sentence ranges, which made "answer more fully" unreachable
    # without editing prompts. brief | standard | detailed.
    answer_detail: str = "standard"
    rerank_top_n: int = 8
    cross_encoder_candidate_limit: int = 16
    # Evidence width for CROSS_SOURCE and CODE_ASSISTED, the default route for
    # most questions. Previously a literal 4 in workflow_nodes/retrieval.py, which
    # made PI_RAG_RERANK_TOP_N inert for the majority of traffic.
    mixed_source_top_n: int = 8
    # CODE_ASSISTED is the default documentation route. PAGE is therefore its
    # primary evidence family; CODE may corroborate it but cannot consume more
    # than two final slots or displace the reserved primary window.
    code_assisted_page_top_n: int = 6
    code_assisted_code_top_n: int = 2
    feature_inventory_top_n: int = 25
    population_contract_max_members: int = 100
    inventory_cross_encoder_candidate_limit: int = 16
    # Phase-2 calibration on the two event questions measured relevant pairs at
    # 0.540-0.912 and related-but-wrong pairs at 0.008-0.030.
    rerank_score_threshold: float = 0.10
    entity_overview_rerank_score_threshold: float = 0.05
    exact_code_rerank_score_threshold: float = 0.65
    exact_code_retrieval_score_floor: float = 0.80
    max_candidates: int = 50
    # Candidate prefilter. It exists to bound cross-encoder cost, so it must
    # remove poor candidates, never a proportion of the pool: the previous rule
    # cut everything below the pool's own median dense score, which discards
    # about half of any pool however good it is. An absolute floor removes only
    # weak matches, and the fraction ceiling keeps a mistuned floor from turning
    # a cost bound into content deletion.
    prefilter_min_dense_score: float = 0.30
    prefilter_max_removed_fraction: float = 0.34
    max_chunks_per_source: int = 3
    max_evidence_tokens: int = 16_000
    adaptive_temperature_enabled: bool = True
    factual_temperature: float = 0.0
    synthesis_temperature: float = 0.1
    translation_enabled: bool = True
    grounding_verification_enabled: bool = True
    incremental_verified_streaming_enabled: bool = True
    # Supported event claims measured 0.880-0.965; false claims peaked at 0.242.
    grounding_score_threshold: float = 0.65
    grounding_cross_language_score_threshold: float = 0.60
    # The cross-encoder scores running text. Rewriting Markdown tables as one
    # sentence per row on the scoring path only (the generator still sees the
    # table) is what lets a faithful restatement of a table row clear the same
    # threshold a restatement of a prose sentence clears.
    linearize_table_evidence: bool = True
    # Set only if a corpus is dominated by tables the linearizer cannot read.
    # Empty means "use grounding_score_threshold for table evidence too".
    grounding_table_evidence_score_threshold: float | None = 0.60

    model_config = SettingsConfigDict(
        env_prefix="PI_RAG_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "ollama":
            return bool(
                self.local_inference_enabled
                and self.ollama_base_url
                and self.ollama_model
                and self.ollama_planner_model
            )
        if self.llm_provider == "openai":
            return bool(
                self.openai_api_key
                and self.openai_budget_model
                and self.openai_standard_model
                and self.openai_complex_model
            )
        credential_configured = (
            self.azure_openai_use_managed_identity or bool(self.azure_openai_api_key)
        )
        return all(
            (self.azure_openai_endpoint, self.azure_openai_deployment, credential_configured)
        )

    def model_for_profile(self, profile: str) -> str:
        if self.llm_provider == "ollama":
            # ASK maps to budget and can use the lighter planner model; ANALYZE and
            # DEEP_ANALYSIS get the generator. When both are the same model, as they
            # are by default, this collapses to one resident model and no swapping.
            return self.ollama_planner_model if profile == "budget" else self.ollama_model
        return {
            "budget": self.openai_budget_model,
            "standard": self.openai_standard_model,
            "complex": self.openai_complex_model,
        }.get(profile, self.openai_standard_model)

    @property
    def allowed_host_list(self) -> list[str]:
        return [value.strip() for value in self.allowed_hosts.split(",") if value.strip()]

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        if not self.supported_embedding_models or not all(self.supported_embedding_models):
            raise ValueError("PI_RAG_SUPPORTED_EMBEDDING_MODELS must not be empty")
        if not self.supported_schema_versions or not all(self.supported_schema_versions):
            raise ValueError("PI_RAG_SUPPORTED_SCHEMA_VERSIONS must not be empty")
        if self.ollama_context_tokens < 4_096 or self.ollama_context_tokens > 262_144:
            raise ValueError(
                "PI_RAG_OLLAMA_CONTEXT_TOKENS must be between 4096 and the model's "
                "native 262144"
            )
        if self.ollama_max_output_tokens < 256 or self.ollama_max_output_tokens > 8_192:
            raise ValueError("PI_RAG_OLLAMA_MAX_OUTPUT_TOKENS must be between 256 and 8192")
        if self.llm_timeout_seconds <= 0:
            raise ValueError("PI_RAG_LLM_TIMEOUT_SECONDS must be greater than zero")
        if self.llm_stream_idle_timeout_seconds <= 0:
            raise ValueError(
                "PI_RAG_LLM_STREAM_IDLE_TIMEOUT_SECONDS must be greater than zero"
            )
        if (
            self.llm_stream_total_timeout_seconds
            <= self.llm_stream_idle_timeout_seconds
        ):
            raise ValueError(
                "PI_RAG_LLM_STREAM_TOTAL_TIMEOUT_SECONDS must exceed "
                "PI_RAG_LLM_STREAM_IDLE_TIMEOUT_SECONDS"
            )
        if self.request_timeout_seconds <= self.llm_stream_total_timeout_seconds:
            raise ValueError(
                "PI_RAG_REQUEST_TIMEOUT_SECONDS must exceed "
                "PI_RAG_LLM_STREAM_TOTAL_TIMEOUT_SECONDS"
            )
        if (
            self.llm_timeout_seconds * self.llm_retry_attempts
            >= self.request_timeout_seconds
        ):
            raise ValueError(
                "PI_RAG_REQUEST_TIMEOUT_SECONDS must exceed the non-streamed LLM "
                "retry budget"
            )
        if self.answer_detail not in {"brief", "standard", "detailed"}:
            raise ValueError(
                "PI_RAG_ANSWER_DETAIL must be brief, standard, or detailed"
            )
        if not 0 <= self.ollama_presence_penalty <= 2:
            raise ValueError("PI_RAG_OLLAMA_PRESENCE_PENALTY must be between 0 and 2")
        if not 0.5 <= self.ollama_repeat_penalty <= 2:
            raise ValueError("PI_RAG_OLLAMA_REPEAT_PENALTY must be between 0.5 and 2")
        if self.prompt_overhead_reserve_tokens < 512:
            raise ValueError("PI_RAG_PROMPT_OVERHEAD_RESERVE_TOKENS must be at least 512")
        fixed_prompt_cost = (
            self.ollama_max_output_tokens
            + self.prompt_overhead_reserve_tokens
            + self.max_conversation_history_tokens
            + self.max_semantic_context_tokens
        )
        if (
            self.llm_provider == "ollama"
            and self.max_evidence_tokens + fixed_prompt_cost > self.ollama_context_tokens
        ):
            raise ValueError(
                "The prompt budget does not fit the context window: "
                f"PI_RAG_MAX_EVIDENCE_TOKENS={self.max_evidence_tokens} plus "
                f"{fixed_prompt_cost} reserved tokens exceeds "
                f"PI_RAG_OLLAMA_CONTEXT_TOKENS={self.ollama_context_tokens}. "
                "Raise the context window or lower the evidence budget."
            )
        if not 0 <= self.prefilter_min_dense_score <= 1:
            raise ValueError("PI_RAG_PREFILTER_MIN_DENSE_SCORE must be between 0 and 1")
        if not 0 <= self.prefilter_max_removed_fraction <= 0.5:
            raise ValueError(
                "PI_RAG_PREFILTER_MAX_REMOVED_FRACTION must be between 0 and 0.5: a "
                "candidate prefilter that may remove more than half the pool is not a "
                "cost bound"
            )
        if self.local_max_concurrency < 1 or self.local_max_concurrency > 4:
            raise ValueError("PI_RAG_LOCAL_MAX_CONCURRENCY must be between 1 and 4")
        if self.max_inflight_requests < 1 or self.max_inflight_requests > 32:
            raise ValueError("PI_RAG_MAX_INFLIGHT_REQUESTS must be between 1 and 32")
        if self.load_shed_wait_seconds <= 0 or self.load_shed_wait_seconds > 5:
            raise ValueError(
                "PI_RAG_LOAD_SHED_WAIT_SECONDS must be greater than 0 and at most 5"
            )
        if self.max_query_variants < 1 or self.max_query_variants > 5:
            raise ValueError("PI_RAG_MAX_QUERY_VARIANTS must be between 1 and 5")
        if self.max_entity_expansions < 0 or self.max_entity_expansions > 20:
            raise ValueError("PI_RAG_MAX_ENTITY_EXPANSIONS must be between 0 and 20")
        if self.max_retrieval_attempts < 1 or self.max_retrieval_attempts > 3:
            raise ValueError("PI_RAG_MAX_RETRIEVAL_ATTEMPTS must be between 1 and 3")
        if self.max_neighbors_per_anchor < 0 or self.max_neighbors_per_anchor > 2:
            raise ValueError("PI_RAG_MAX_NEIGHBORS_PER_ANCHOR must be between 0 and 2")
        if self.lexical_fusion_weight <= 0 or self.dense_fusion_weight <= 0:
            raise ValueError("Hybrid fusion weights must be greater than zero")
        if not 0 <= self.source_volume_discount_strength <= 1:
            raise ValueError(
                "PI_RAG_SOURCE_VOLUME_DISCOUNT_STRENGTH must be between 0 and 1"
            )
        if self.feature_inventory_top_n < 2 or self.feature_inventory_top_n > 25:
            raise ValueError("PI_RAG_FEATURE_INVENTORY_TOP_N must be between 2 and 25")
        if not 1 <= self.population_contract_max_members <= 500:
            raise ValueError(
                "PI_RAG_POPULATION_CONTRACT_MAX_MEMBERS must be between 1 and 500"
            )
        if (
            self.inventory_cross_encoder_candidate_limit < 4
            or self.inventory_cross_encoder_candidate_limit > 25
        ):
            raise ValueError(
                "PI_RAG_INVENTORY_CROSS_ENCODER_CANDIDATE_LIMIT must be between 4 and 25"
            )
        if self.dependency_retry_attempts < 1 or self.dependency_retry_attempts > 5:
            raise ValueError("PI_RAG_DEPENDENCY_RETRY_ATTEMPTS must be between 1 and 5")
        if self.lexical_fallback_max_records < 100 or self.lexical_fallback_max_records > 20_000:
            raise ValueError("PI_RAG_LEXICAL_FALLBACK_MAX_RECORDS must be between 100 and 20000")
        if self.lexical_fallback_cache_ttl_seconds < 0 or self.lexical_fallback_cache_ttl_seconds > 3600:
            raise ValueError("PI_RAG_LEXICAL_FALLBACK_CACHE_TTL_SECONDS must be between 0 and 3600")
        if self.embedding_dimensions not in {384, 768, 1024}:
            raise ValueError("PI_RAG_EMBEDDING_DIMENSIONS must be 384, 768, or 1024")
        if self.local_embedding_batch_size < 1 or self.local_embedding_batch_size > 64:
            raise ValueError("PI_RAG_LOCAL_EMBEDDING_BATCH_SIZE must be between 1 and 64")
        if self.local_rerank_batch_size < 1 or self.local_rerank_batch_size > 128:
            raise ValueError("PI_RAG_LOCAL_RERANK_BATCH_SIZE must be between 1 and 128")
        if not self.local_embedding_model:
            raise ValueError("PI_RAG_LOCAL_EMBEDDING_MODEL is required for local embedding")
        if not 0 <= self.grounding_score_threshold <= 1:
            raise ValueError("PI_RAG_GROUNDING_SCORE_THRESHOLD must be between 0 and 1")
        if not 0 <= self.grounding_cross_language_score_threshold <= self.grounding_score_threshold:
            raise ValueError(
                "PI_RAG_GROUNDING_CROSS_LANGUAGE_SCORE_THRESHOLD must be between 0 and the normal grounding threshold"
            )
        if self.grounding_table_evidence_score_threshold is not None and not (
            0 <= self.grounding_table_evidence_score_threshold <= self.grounding_score_threshold
        ):
            raise ValueError(
                "PI_RAG_GROUNDING_TABLE_EVIDENCE_SCORE_THRESHOLD must be between 0 and the normal grounding threshold"
            )
        if not 0 <= self.exact_code_rerank_score_threshold <= 1:
            raise ValueError(
                "PI_RAG_EXACT_CODE_RERANK_SCORE_THRESHOLD must be between 0 and 1"
            )
        if not 0 <= self.entity_overview_rerank_score_threshold <= self.rerank_score_threshold:
            raise ValueError(
                "PI_RAG_ENTITY_OVERVIEW_RERANK_SCORE_THRESHOLD must be between 0 and the normal rerank threshold"
            )
        if not 0 <= self.exact_code_retrieval_score_floor <= 1:
            raise ValueError("PI_RAG_EXACT_CODE_RETRIEVAL_SCORE_FLOOR must be between 0 and 1")
        if not 0 <= self.factual_temperature <= 0.2:
            raise ValueError("PI_RAG_FACTUAL_TEMPERATURE must be between 0 and 0.2")
        if not self.factual_temperature <= self.synthesis_temperature <= 0.2:
            raise ValueError(
                "PI_RAG_SYNTHESIS_TEMPERATURE must be between the factual temperature and 0.2"
            )
        environment = self.environment.strip().lower()
        if environment != "development" and len(self.internal_api_key) < 32:
            raise ValueError(
                "PI_RAG_INTERNAL_API_KEY must contain at least 32 characters "
                "outside development"
            )
        if environment == "production":
            missing = []
            if len(self.internal_api_key) < 32:
                missing.append("PI_RAG_INTERNAL_API_KEY")
            if not self.chroma_host or self.chroma_port < 1 or not self.chroma_collection:
                missing.append("PI_RAG_CHROMA_HOST, PI_RAG_CHROMA_PORT, and PI_RAG_CHROMA_COLLECTION")
            if self.llm_provider not in {"ollama", "openai", "azure-openai"}:
                missing.append("PI_RAG_LLM_PROVIDER must be ollama, openai, or azure-openai")
            if not self.llm_configured:
                missing.append("the selected production LLM settings")
            if self.llm_provider == "azure-openai" and not self.azure_openai_use_managed_identity:
                missing.append("PI_RAG_AZURE_OPENAI_USE_MANAGED_IDENTITY")
            if self.docs_enabled:
                missing.append("PI_RAG_DOCS_ENABLED must be false")
            if not self.force_https:
                missing.append("PI_RAG_FORCE_HTTPS must be true")
            if not self.allowed_host_list or "*" in self.allowed_host_list:
                missing.append("PI_RAG_ALLOWED_HOSTS must contain explicit hosts")
            if missing:
                raise ValueError("Unsafe production RAG configuration: " + ", ".join(missing))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
