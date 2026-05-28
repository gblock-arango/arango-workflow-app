from app.compat import StrEnum
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.middleware.strip_service_prefix import normalize_service_url_path_prefix


def _resolved_env_files() -> tuple[str, ...]:
    """Paths to optional `.env` files — stable regardless of process cwd.

    - Databricks App layout: repo-root ``.env`` (src/app/config → ../../../.env).
    - Legacy monorepo: ``backend/app/config`` → repo-root ``.env``.
    - Flat deploy ``/project``: ``/project/.env`` beside ``app/``.

    A cwd-relative ``../.env`` breaks when cwd is ``/project`` (becomes ``/.env``).
    """
    here = Path(__file__).resolve()
    bundle = here.parents[1] / ".env"
    paths: list[Path] = []
    if len(here.parents) >= 3:
        repo = here.parents[2] / ".env"
        if here.parents[2] != Path("/") and repo.is_file():
            paths.append(repo)
    if bundle.is_file() and bundle.resolve() not in {p.resolve() for p in paths}:
        paths.append(bundle)
    return tuple(str(p) for p in paths)


class DeploymentMode(StrEnum):
    LOCAL_DEV = "local_dev"
    SELF_MANAGED_PLATFORM = "self_managed_platform"
    MANAGED_PLATFORM = "managed_platform"


class LlmProvider(StrEnum):
    """How LangGraph extraction and chunk embeddings reach LLMs."""

    AUTO = "auto"
    DATABRICKS_SERVING = "databricks_serving"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_resolved_env_files() or None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_log_level: str = "INFO"
    app_secret_key: str = "change-this"
    #: When false (Databricks default), ``/api/v1`` uses a service mock user — no HS256 JWT or APP_SECRET_KEY.
    #: Peer BFF under ``/api/workflow`` is always public. Set true only if you enable scaffold login/JWT.
    jwt_auth_enabled: bool = False

    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    backend_workers: int = 1

    # -- Deployment Mode ---------------------------------------------------
    test_deployment_mode: DeploymentMode = DeploymentMode.LOCAL_DEV

    # -- ArangoDB (common) -------------------------------------------------
    arango_host: str = "http://localhost:8530"
    arango_db: str = "OntoExtract"
    arango_user: str = "root"
    arango_password: str = "changeme"
    arango_no_auth: bool = False

    # -- ArangoDB (cluster / self-managed) ---------------------------------
    arango_endpoint: str = ""
    arango_verify_ssl: bool = True
    arango_timeout: int = 30

    # -- ArangoDB (AMP / managed platform — future ArangoDB 4.0) -----------
    arango_graph_api_key_id: str = ""
    arango_graph_api_key_secret: str = ""
    gae_deployment_mode: str = ""

    # -- Redis -------------------------------------------------------------
    #: In k8s set ``REDIS_URL`` to your Redis Service (not localhost). If Redis is
    #: unreachable, rate limiting degrades to pass-through (see ``rate_limit.py``).
    #: To disable limits entirely: ``RATE_LIMIT_ENABLED=false``.
    redis_url: str = "redis://localhost:6379/0"

    # -- LLM ---------------------------------------------------------------
    openai_api_key: str = ""
    openai_base_url: str = ""
    anthropic_api_key: str = ""
    llm_extraction_model: str = "claude-sonnet-4-20250514"
    embedding_model: str = "text-embedding-3-small"
    #: ``auto`` on Databricks uses Model Serving when ``AUTOGRAPH_*_MODEL_NAME`` or resolve
    #: queries are set; ``openai`` / ``anthropic`` force external APIs; ``databricks_serving``
    #: requires workspace OAuth and serving endpoint names.
    autograph_llm_provider: str = Field(
        default="auto",
        validation_alias=AliasChoices(
            "AUTOGRAPH_LLM_PROVIDER",
            "LLM_PROVIDER",
        ),
    )
    #: Databricks serving endpoint **name** for LangGraph extraction (not a full URL).
    autograph_llm_model_name: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AUTOGRAPH_LLM_MODEL_NAME",
            "LLM_SERVING_ENDPOINT",
        ),
    )
    autograph_llm_resolve_query: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AUTOGRAPH_LLM_RESOLVE_QUERY",
            "AUTOGRAPH_LLM_FOUNDATION_MODEL_QUERY",
        ),
    )
    #: Databricks serving endpoint **name** for chunk/ER embeddings.
    autograph_embedding_model_name: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AUTOGRAPH_EMBEDDING_MODEL_NAME",
            "EMBEDDING_SERVING_ENDPOINT",
            "AUTOGRAPH_EMBEDDING_SERVING_ENDPOINT",
        ),
    )
    autograph_embedding_resolve_query: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AUTOGRAPH_EMBEDDING_RESOLVE_QUERY",
            "AUTOGRAPH_EMBEDDING_FOUNDATION_MODEL_QUERY",
        ),
    )
    autograph_resolve_endpoint_deep: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "AUTOGRAPH_RESOLVE_ENDPOINT_DEEP",
            "AUTOGRAPH_LLM_RESOLVE_ENDPOINT_DEEP",
        ),
    )
    #: Vector index dimension for ``chunks.embedding`` (0 = infer from model/provider).
    autograph_embedding_dimension: int = Field(
        default=0,
        validation_alias=AliasChoices(
            "AUTOGRAPH_EMBEDDING_DIMENSION",
            "EMBEDDING_DIMENSION",
        ),
    )
    #: Per-request HTTP timeout for LLM calls, in seconds. Without an
    #: explicit timeout, ``ChatAnthropic`` and ``ChatOpenAI`` inherit
    #: their underlying httpx client default (``None`` = wait forever
    #: in the SDK builds we depend on), so a hung provider connection
    #: ties up the asyncio task indefinitely. With a single uvicorn
    #: worker, enough hung tasks starve the threadpool and the API
    #: stops responding to anything -- exactly the symptom we hit
    #: during the WTW Ontology document load (worker in ``S 0%``,
    #: ``/runs`` healthcheck timing out, REST poll fallbacks failing
    #: into the WS connection storm).
    #:
    #: 60s is a deliberately generous ceiling: the qualitative-eval
    #: map step legitimately needs 30-45s on long chunks under the
    #: GPT-4o tier, while a real outage will trip well inside the
    #: minute. Tune downward in production if your deployment fronts
    #: a cheaper / faster judge model.
    llm_request_timeout_seconds: float = 60.0

    # -- Extraction --------------------------------------------------------
    extraction_passes: int = 3
    extraction_consistency_threshold: int = 2
    extraction_confidence_min: float = 0.6
    #: Maximum simultaneous LLM calls in the extractor (all passes × batches).
    #: Default 40 is fast on high TPM tiers; lower to 3–8 on OpenAI free/Tier-1
    #: accounts to avoid 429 token-per-minute errors.
    llm_extraction_max_concurrency: int = 40
    #: Maximum simultaneous LLM calls fired by the qualitative-evaluation
    #: map phase. Caps unbounded ``asyncio.gather`` fan-out that, on large
    #: documents, can produce dozens of parallel OpenAI requests, trip
    #: provider rate limits, trigger long retry storms, and saturate the
    #: single uvicorn worker (blocking unrelated API + WebSocket traffic).
    #: A value of 5 keeps us well under typical TPM/RPM ceilings while
    #: preserving most of the speed-up from concurrency.
    qualitative_eval_max_concurrency: int = 5

    # -- Entity Resolution -------------------------------------------------
    er_vector_similarity_threshold: float = 0.85
    er_vector_weight: float = 0.6
    er_topo_weight: float = 0.4

    # -- Belief Revision (PRD §6.16, Stream 11) ----------------------------
    #: Master kill-switch for the confidence-decay job (IBR.3). Default OFF;
    #: dry-runs (``apply_confidence_decay(..., dry_run=True)``) work even
    #: when this is False, so an admin can preview decay before enabling.
    belief_revision_decay_enabled: bool = False
    #: Half-life for the decay curve. After this many days an
    #: untouched class's confidence has halved (subject to the floor).
    belief_revision_decay_half_life_days: float = 90.0
    #: Hard floor for decayed confidence; we never decay below this so
    #: a long-untouched class is always still ranked above a brand-new
    #: zero-confidence one. Tune per ontology if needed.
    belief_revision_decay_floor: float = 0.05
    #: Master kill-switch for the per-document Belief Revision pipeline
    #: stage (IBR.10/11). Default OFF: every new upload runs the legacy
    #: extract+ER+filter path with no touchpoint discovery, no LLM
    #: revision agent, and no temporal supersedes. Flip to True to
    #: activate the four-phase IBR pipeline. Setting only -- no code
    #: deploy required to roll out or roll back.
    belief_revision_pipeline_enabled: bool = False
    #: Circuit breaker for the LLM revision agent (IBR.18). Maximum
    #: number of revisions allowed within ``circuit_window_seconds``
    #: before the breaker trips and halts the agent until the next
    #: window. Defaults are conservative: 50 / 60s allows realistic
    #: extraction loads while preventing runaway LLM cost. Set
    #: ``max_per_minute`` to 0 to disable the breaker entirely.
    belief_revision_circuit_max_per_minute: int = 50
    belief_revision_circuit_window_seconds: float = 60.0

    # -- Ontology Defaults ---------------------------------------------------
    default_ontology_uri: str = "http://example.org/ontology#"

    # -- CORS ---------------------------------------------------------------
    cors_origins: str = "http://localhost:3000"

    # -- Public URL (reverse proxy / Container Manager) --------------------
    #: External path prefix before routes (env ``SERVICE_URL_PATH_PREFIX``).
    #: Must match the frontend static bundle / Next ``basePath`` (same env in repo ``.env``).
    service_url_path_prefix: str = ""

    #: Next.js static export root (directory containing ``index.html`` and ``_next/``).
    #: Use in k8s when the UI is copied or mounted at a known path. If unset, the app
    #: looks for ``<bundle>/frontend/out``, monorepo ``frontend/out``, or ``/app/static``.
    #: Build the export with ``AOE_STATIC_EXPORT=1`` and ``SERVICE_URL_PATH_PREFIX`` (see
    #: ``scripts/package-arango-manual.sh`` with ``PACKAGE_INCLUDE_FRONTEND=1``).
    frontend_static_root: str = Field(
        default="",
        validation_alias=AliasChoices("AOE_FRONTEND_OUT_DIR", "FRONTEND_STATIC_ROOT"),
    )

    # -- Rate Limiting -----------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_default: int = 100
    rate_limit_default_tier: str = "standard"

    # -- Admin -------------------------------------------------------------
    allow_system_reset: bool = False

    @field_validator("app_secret_key", mode="after")
    @classmethod
    def _validate_secret_key(cls, v: str, info: Any) -> str:
        env = info.data.get("app_env", "development")
        jwt_on = bool(info.data.get("jwt_auth_enabled", False))
        if jwt_on and env == "production" and v in ("change-this", ""):
            raise ValueError("APP_SECRET_KEY must be set when JWT_AUTH_ENABLED=true and APP_ENV=production")
        return v

    @field_validator("test_deployment_mode", mode="before")
    @classmethod
    def _normalize_deployment_mode(cls, v: str) -> str:
        if isinstance(v, str):
            s = v.strip().lower()
            if s == "local_docker":
                return DeploymentMode.LOCAL_DEV.value
            return s
        return v

    @field_validator("service_url_path_prefix", mode="after")
    @classmethod
    def _normalize_service_url_path_prefix_setting(cls, v: str) -> str:
        return normalize_service_url_path_prefix(v)

    # -- Deployment-mode-derived properties --------------------------------

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_local(self) -> bool:
        return self.test_deployment_mode == DeploymentMode.LOCAL_DEV

    @property
    def is_cluster(self) -> bool:
        return self.test_deployment_mode in (
            DeploymentMode.SELF_MANAGED_PLATFORM,
            DeploymentMode.MANAGED_PLATFORM,
        )

    @property
    def is_amp(self) -> bool:
        return self.test_deployment_mode == DeploymentMode.MANAGED_PLATFORM

    @property
    def effective_arango_host(self) -> str:
        """Resolve the ArangoDB endpoint based on deployment mode.

        - local_dev: uses ARANGO_HOST when not using gateway (legacy; prefer gateway)
        - self_managed_platform / managed_platform: uses ARANGO_ENDPOINT
        """
        if self.is_local:
            return self.arango_host
        if self.arango_endpoint:
            return self.arango_endpoint
        return self.arango_host

    @property
    def has_gae(self) -> bool:
        """Graph Analytics Engine is only available on cluster deployments."""
        return self.is_cluster

    @property
    def has_smart_graphs(self) -> bool:
        """SmartGraphs require a cluster (Enterprise Edition)."""
        return self.is_cluster

    @property
    def can_create_databases(self) -> bool:
        """On managed platforms, DB creation may be restricted.

        Local and self-managed allow _system DB access for auto-creation.
        AMP managed platform may not.
        """
        return not self.is_amp

    @property
    def supports_satellite_collections(self) -> bool:
        """SatelliteCollections are cluster-only (Enterprise Edition)."""
        return self.is_cluster

    @property
    def llm_provider_normalized(self) -> LlmProvider:
        raw = (self.autograph_llm_provider or "auto").strip().lower()
        try:
            return LlmProvider(raw)
        except ValueError:
            return LlmProvider.AUTO

    def _databricks_serving_configured_for_chat(self) -> bool:
        return bool(
            (self.autograph_llm_model_name or "").strip()
            or (self.autograph_llm_resolve_query or "").strip()
        )

    def _databricks_serving_configured_for_embeddings(self) -> bool:
        return bool(
            (self.autograph_embedding_model_name or "").strip()
            or (self.autograph_embedding_resolve_query or "").strip()
        )

    def use_databricks_for_extraction(self) -> bool:
        provider = self.llm_provider_normalized
        if provider == LlmProvider.DATABRICKS_SERVING:
            return True
        if provider in (LlmProvider.OPENAI, LlmProvider.ANTHROPIC):
            return False
        if not self.is_cluster:
            return False
        return self._databricks_serving_configured_for_chat()

    def use_databricks_for_embeddings(self) -> bool:
        provider = self.llm_provider_normalized
        if provider == LlmProvider.DATABRICKS_SERVING:
            return True
        if provider in (LlmProvider.OPENAI, LlmProvider.ANTHROPIC):
            return False
        if not self.is_cluster:
            return False
        return self._databricks_serving_configured_for_embeddings()

    @property
    def effective_embedding_dimension(self) -> int:
        if self.autograph_embedding_dimension > 0:
            return int(self.autograph_embedding_dimension)
        if self.use_databricks_for_embeddings():
            from app.llm.databricks_serving import (
                effective_embedding_model_name,
                default_embedding_dimension_for_model,
            )

            return default_embedding_dimension_for_model(effective_embedding_model_name())
        model = (self.embedding_model or "").lower()
        if "text-embedding-3" in model or "ada" in model:
            return 1536
        return 1536

    @property
    def wcc_backend_preference(self) -> str:
        """Entity resolution WCC clustering backend.

        GAE backend is faster but only available on clusters.
        Falls back to in-memory Python Union-Find on single server.
        """
        if self.has_gae:
            return "gae"
        return "python_union_find"


settings = Settings()
