"""Databricks Model Serving via workspace OAuth and OpenAI-compatible ``/serving-endpoints``."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import TYPE_CHECKING

from openai import AsyncOpenAI, OpenAI

from app.llm.foundation_model_endpoint_resolver import resolve_serving_endpoint_name

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)

# Common Databricks foundation embedding endpoints (1024-dim English models).
_DATABRICKS_EMBEDDING_DIM_DEFAULT = 1024
_OPENAI_EMBEDDING_DIM_DEFAULT = 1536

# Foundation Model APIs — preconfigured pay-per-token serving endpoints (instantly available).
# Models are registered in Unity Catalog as ``system.ai.*``; invoke by **endpoint name**, not UC path.
# Databricks no longer recommends Marketplace installs for GTE/BGE — use these endpoints instead.
# https://docs.databricks.com/en/machine-learning/foundation-model-apis/supported-models
_FOUNDATION_MODEL_EMBEDDING_ALIASES: dict[str, str] = {
    "bge_large_en_v1_5": "databricks-bge-large-en",
    "bge-large-en-v1.5": "databricks-bge-large-en",
    "baai/bge-large-en-v1.5": "databricks-bge-large-en",
    "gte_large_en_v1_5": "databricks-gte-large-en",
    "gte-large-en-v1.5": "databricks-gte-large-en",
}


def normalize_serving_endpoint_name(name: str) -> str:
    """Map common BGE/GTE ids to Foundation Model API serving endpoint names."""
    raw = (name or "").strip()
    if not raw:
        return raw
    if raw.startswith("databricks-"):
        return raw
    key = raw.lower().replace("-", "_").replace("/", "_")
    return _FOUNDATION_MODEL_EMBEDDING_ALIASES.get(key, raw)


def _running_in_databricks_app() -> bool:
    if (os.environ.get("DATABRICKS_APP_PORT") or "").strip():
        return True
    if (os.environ.get("DATABRICKS_APP_NAME") or "").strip():
        return True
    sc = (os.environ.get("DATABRICKS_SOURCE_CODE_PATH") or "").strip().lower()
    if sc and "/app/python" in sc:
        return True
    try:
        cwd = os.getcwd().lower()
    except OSError:
        cwd = ""
    if "/app/python" in cwd or cwd.startswith("/app/"):
        return True
    return False


def workspace_client() -> WorkspaceClient:
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient()


def _workspace_bearer_token(ws: WorkspaceClient) -> str:
    host = (ws.config.host or "").strip().rstrip("/")
    if not host:
        raise ValueError("Workspace host is empty (configure DATABRICKS_HOST / SDK).")
    auth = ws.config.authenticate() or {}
    lower = {str(k).lower(): v for k, v in auth.items()}
    bearer = str(lower.get("authorization") or "").strip()
    if bearer.lower().startswith("bearer "):
        token = bearer[7:].strip()
    else:
        token = str(lower.get("token") or "").strip()
    if not token:
        raise ValueError(
            "Could not obtain a bearer token from WorkspaceClient.config.authenticate(); "
            "Databricks Model Serving needs workspace OAuth (Databricks App runtime or SDK auth)."
        )
    return token


def _serving_base_url(ws: WorkspaceClient) -> str:
    host = (ws.config.host or "").strip().rstrip("/")
    if not host:
        raise ValueError("Workspace host is empty (configure DATABRICKS_HOST / SDK).")
    return f"{host}/serving-endpoints"


def workspace_openai_client(ws: WorkspaceClient | None = None) -> OpenAI:
    """Sync OpenAI client pointed at ``{host}/serving-endpoints``."""
    client_ws = ws or workspace_client()
    return OpenAI(api_key=_workspace_bearer_token(client_ws), base_url=_serving_base_url(client_ws))


def workspace_async_openai_client(ws: WorkspaceClient | None = None) -> AsyncOpenAI:
    """Async OpenAI client pointed at ``{host}/serving-endpoints``."""
    from langchain_openai.chat_models._client_utils import _get_default_async_httpx_client

    from app.config import settings

    client_ws = ws or workspace_client()
    base_url = _serving_base_url(client_ws)
    timeout = float(settings.llm_request_timeout_seconds)
    http_client = _get_default_async_httpx_client(base_url, timeout)
    return AsyncOpenAI(
        api_key=_workspace_bearer_token(client_ws),
        base_url=base_url,
        timeout=timeout,
        http_client=http_client,
    )


def resolve_serving_endpoint_name_sync(
    model_query: str,
    *,
    deep: bool | None = None,
    require_ready: bool = True,
) -> str | None:
    from app.config import settings

    q = (model_query or "").strip()
    if not q:
        return None
    use_deep = settings.autograph_resolve_endpoint_deep if deep is None else deep
    return resolve_serving_endpoint_name(
        workspace_client(),
        q,
        deep=use_deep,
        require_ready=require_ready,
    )


@lru_cache(maxsize=4)
def _resolved_endpoint_cached(kind: str, explicit: str, query: str, deep: bool) -> str:
    """Cache resolved endpoint names (process lifetime; env changes need restart)."""
    name = normalize_serving_endpoint_name((explicit or "").strip())
    if name:
        return name
    q = (query or "").strip()
    if not q:
        raise ValueError(f"AUTOGRAPH_{kind.upper()}_MODEL_NAME or resolve query is required for Databricks serving")
    resolved = resolve_serving_endpoint_name_sync(q, deep=deep)
    if not resolved:
        raise ValueError(
            f"No READY serving endpoint matched query {q!r} for AUTOGRAPH_{kind.upper()}_* "
            f"(set AUTOGRAPH_{kind.upper()}_MODEL_NAME explicitly or fix AUTOGRAPH_{kind.upper()}_RESOLVE_QUERY)"
        )
    logger.info("Resolved AUTOGRAPH %s serving endpoint %r from query %r", kind, resolved, q)
    return resolved


def resolved_chat_model_name() -> str:
    from app.config import settings

    return _resolved_endpoint_cached(
        "llm",
        settings.autograph_llm_model_name,
        settings.autograph_llm_resolve_query,
        settings.autograph_resolve_endpoint_deep,
    )


def resolved_embedding_model_name() -> str:
    from app.config import settings

    return _resolved_endpoint_cached(
        "embedding",
        settings.autograph_embedding_model_name,
        settings.autograph_embedding_resolve_query,
        settings.autograph_resolve_endpoint_deep,
    )


def uses_databricks_serving_for_extraction() -> bool:
    from app.config import settings

    return settings.use_databricks_for_extraction()


def uses_databricks_serving_for_embeddings() -> bool:
    from app.config import settings

    return settings.use_databricks_for_embeddings()


def effective_embedding_model_name() -> str:
    from app.config import settings

    if settings.use_databricks_for_embeddings():
        return resolved_embedding_model_name()
    return settings.embedding_model


def effective_extraction_model_name(requested: str | None = None) -> str:
    """Serving endpoint or provider model name for ``_get_llm``."""
    from app.config import settings

    if settings.use_databricks_for_extraction():
        return resolved_chat_model_name()
    return (requested or settings.llm_extraction_model).strip()


def default_embedding_dimension_for_model(model_name: str) -> int:
    """Best-effort dimension hint when ``AUTOGRAPH_EMBEDDING_DIMENSION`` is unset."""
    m = (model_name or "").lower()
    if "text-embedding-3" in m or "ada" in m:
        return _OPENAI_EMBEDDING_DIM_DEFAULT
    if "bge-small" in m or "bge_small" in m:
        return 384
    if "bge-base" in m or "bge_base" in m:
        return 768
    if any(token in m for token in ("bge", "gte", "e5", "qwen", "embedding", "databricks-")):
        return _DATABRICKS_EMBEDDING_DIM_DEFAULT
    return _OPENAI_EMBEDDING_DIM_DEFAULT
