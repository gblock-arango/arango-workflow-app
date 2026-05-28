#!/usr/bin/env python3
"""Summarize Model Serving endpoint readiness for Autograph (AUTOGRAPH_* model names).

Uses :class:`databricks.sdk.WorkspaceClient` (same auth as ``deploy_app.sh``).

Reads ``AUTOGRAPH_LLM_MODEL_NAME`` and ``AUTOGRAPH_EMBEDDING_MODEL_NAME`` (and legacy
``LLM_SERVING_ENDPOINT`` / ``EMBEDDING_SERVING_ENDPOINT`` if set in the environment).
"""

from __future__ import annotations

import os
import sys


def _entity_hint(se) -> str:
    if se is None:
        return ""
    fm = getattr(se, "foundation_model", None)
    if fm is not None:
        name = getattr(fm, "name", None)
        if name:
            return f"foundation_model={name!r}"
    en = getattr(se, "entity_name", None) or ""
    ev = getattr(se, "entity_version", None) or ""
    if en:
        return f"entity_name={en!r}" + (f"@{ev!r}" if ev else "")
    em = getattr(se, "external_model", None)
    if em is not None:
        return f"external_model={getattr(em, 'name', em)!r}"
    return ""


def _normalize_embedding_endpoint(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return raw
    try:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        src = str(root / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        from app.llm.databricks_serving import normalize_serving_endpoint_name

        return normalize_serving_endpoint_name(raw)
    except Exception as exc:
        print(f"NOTE: could not normalize embedding endpoint {raw!r}: {exc}", file=sys.stderr)
        return raw


def _collect_endpoint_names() -> list[tuple[str, str]]:
    llm_keys = ("AUTOGRAPH_LLM_MODEL_NAME", "LLM_SERVING_ENDPOINT")
    emb_keys = (
        "AUTOGRAPH_EMBEDDING_MODEL_NAME",
        "EMBEDDING_SERVING_ENDPOINT",
        "AUTOGRAPH_EMBEDDING_SERVING_ENDPOINT",
    )
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for env_key in llm_keys:
        v = (os.environ.get(env_key) or "").strip()
        if v and v not in seen:
            seen.add(v)
            pairs.append((env_key, v))
    for env_key in emb_keys:
        v = (os.environ.get(env_key) or "").strip()
        if not v:
            continue
        resolved = _normalize_embedding_endpoint(v)
        if resolved and resolved not in seen:
            seen.add(resolved)
            pairs.append((env_key, resolved))
    return pairs


def main() -> int:
    uniq = _collect_endpoint_names()
    if not uniq:
        print(
            "ensure_serving_endpoints: no AUTOGRAPH_LLM_MODEL_NAME or "
            "AUTOGRAPH_EMBEDDING_MODEL_NAME set — skip."
        )
        return 0

    try:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.errors import NotFound, ResourceDoesNotExist
    except ImportError as exc:
        print(f"ensure_serving_endpoints: databricks-sdk not importable: {exc}", file=sys.stderr)
        return 0

    try:
        w = WorkspaceClient()
    except Exception as exc:
        print(f"ensure_serving_endpoints: WorkspaceClient() failed: {exc}", file=sys.stderr)
        return 0

    print("ensure_serving_endpoints: WorkspaceClient serving-endpoints summary")
    exit_status = 0
    for env_key, name in uniq:
        print(f"  [{env_key}] -> {name!r}")
        try:
            ep = w.serving_endpoints.get(name)
        except (NotFound, ResourceDoesNotExist):
            print(
                "    NOT FOUND. Open **Serving** in the workspace and copy the exact endpoint name."
            )
            exit_status = 1
            continue
        except Exception as exc:
            print(f"    ERROR: {exc}")
            exit_status = 1
            continue

        st = ep.state
        ready = getattr(st, "ready", None) if st else None
        ready_v = getattr(ready, "value", ready)
        cu = getattr(st, "config_update", None) if st else None
        cu_v = getattr(cu, "value", cu)
        print(f"    state.ready={ready_v!r} state.config_update={cu_v!r}")

        cfg = ep.config
        entities = (cfg.served_entities or []) if cfg else []
        if entities:
            for i, se in enumerate(entities[:3]):
                hint = _entity_hint(se)
                print(f"    served_entities[{i}]: {hint or repr(se)}")
            if len(entities) > 3:
                print(f"    … and {len(entities) - 3} more served_entities")

        if ready_v and str(ready_v).upper() != "READY":
            exit_status = 1

    if exit_status != 0:
        print(
            "ensure_serving_endpoints: one or more endpoints missing or not READY "
            "(Autograph LLM/embeddings will fail until fixed).",
            file=sys.stderr,
        )
    return exit_status


if __name__ == "__main__":
    raise SystemExit(main())
