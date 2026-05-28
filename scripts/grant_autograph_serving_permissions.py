#!/usr/bin/env python3
"""Grant CAN_QUERY on Model Serving endpoints to a Databricks App service principal.

Use when endpoints were not declared in ``app.yaml`` resources, or to repair ACLs after
renaming endpoints. Declaring ``serving_endpoint`` resources with ``permission: CAN_QUERY``
in ``app.yaml`` is preferred — the platform grants on deploy automatically.

Example::

  ./scripts/grant_autograph_serving_permissions.py \\
    --app-name arango-workflow-app \\
    --endpoint databricks-meta-llama-3-3-70b-instruct \\
    --endpoint databricks-bge-large-en
"""

from __future__ import annotations

import argparse
import os
import sys


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


def _endpoint_names_from_env() -> list[str]:
    llm_keys = ("AUTOGRAPH_LLM_MODEL_NAME", "LLM_SERVING_ENDPOINT")
    emb_keys = (
        "AUTOGRAPH_EMBEDDING_MODEL_NAME",
        "EMBEDDING_SERVING_ENDPOINT",
        "AUTOGRAPH_EMBEDDING_SERVING_ENDPOINT",
    )
    out: list[str] = []
    seen: set[str] = set()
    for key in llm_keys:
        v = (os.environ.get(key) or "").strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    for key in emb_keys:
        v = (os.environ.get(key) or "").strip()
        if not v:
            continue
        resolved = _normalize_embedding_endpoint(v)
        if resolved and resolved not in seen:
            seen.add(resolved)
            out.append(resolved)
    return out


def _acl_entry_key(entry: object) -> tuple[str, str]:
    for field in ("service_principal_name", "user_name", "group_name"):
        val = getattr(entry, field, None)
        if val:
            return field, str(val)
    return "", ""


def _permission_rank(level: object) -> int:
    from databricks.sdk.service.serving import ServingEndpointPermissionLevel

    name = getattr(level, "value", level)
    s = str(name).upper()
    if "MANAGE" in s:
        return 3
    if "QUERY" in s:
        return 2
    if "VIEW" in s:
        return 1
    return 0


def grant_can_query(
    w: object,
    *,
    endpoint_name: str,
    service_principal_id: str,
) -> bool:
    from databricks.sdk.service.serving import (
        ServingEndpointAccessControlRequest,
        ServingEndpointPermissionLevel,
    )

    se_api = w.serving_endpoints  # type: ignore[attr-defined]
    try:
        current = se_api.get_permissions(endpoint_name)
    except Exception as exc:
        print(f"ERROR: get_permissions({endpoint_name!r}): {exc}", file=sys.stderr)
        return False

    acl = list(getattr(current, "access_control_list", None) or [])
    sp_field = "service_principal_name"
    merged: list[ServingEndpointAccessControlRequest] = []
    found = False
    for entry in acl:
        kind, ident = _acl_entry_key(entry)
        if kind == sp_field and ident == service_principal_id:
            found = True
            level = getattr(entry, "permission_level", None)
            if _permission_rank(level) >= _permission_rank(ServingEndpointPermissionLevel.CAN_QUERY):
                print(
                    f"OK: {endpoint_name!r} — SP already has "
                    f"{getattr(level, 'value', level)!r}"
                )
                return True
            merged.append(
                ServingEndpointAccessControlRequest(
                    service_principal_name=service_principal_id,
                    permission_level=ServingEndpointPermissionLevel.CAN_QUERY,
                )
            )
        else:
            merged.append(
                ServingEndpointAccessControlRequest(
                    group_name=getattr(entry, "group_name", None),
                    user_name=getattr(entry, "user_name", None),
                    service_principal_name=getattr(entry, "service_principal_name", None),
                    permission_level=getattr(entry, "permission_level", None),
                )
            )

    if not found:
        merged.append(
            ServingEndpointAccessControlRequest(
                service_principal_name=service_principal_id,
                permission_level=ServingEndpointPermissionLevel.CAN_QUERY,
            )
        )

    try:
        se_api.set_permissions(endpoint_name, access_control_list=merged)
    except Exception as exc:
        print(
            f"ERROR: set_permissions({endpoint_name!r}, SP={service_principal_id!r}): {exc}",
            file=sys.stderr,
        )
        return False

    print(f"OK: CAN_QUERY on {endpoint_name!r} for app SP {service_principal_id!r}")
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--app-name", default="arango-workflow-app")
    p.add_argument(
        "--service-principal-id",
        default="",
        help="App SP application id (default: from apps.get)",
    )
    p.add_argument(
        "--endpoint",
        action="append",
        default=[],
        help="Serving endpoint name (repeatable). Default: AUTOGRAPH_* env vars.",
    )
    args = p.parse_args()

    endpoints = [e.strip() for e in args.endpoint if (e or "").strip()]
    if not endpoints:
        endpoints = _endpoint_names_from_env()
    if not endpoints:
        print(
            "ERROR: no endpoints (pass --endpoint or set AUTOGRAPH_LLM_MODEL_NAME / "
            "AUTOGRAPH_EMBEDDING_MODEL_NAME).",
            file=sys.stderr,
        )
        return 2

    try:
        from databricks.sdk import WorkspaceClient
    except ImportError as exc:
        print(f"ERROR: databricks-sdk: {exc}", file=sys.stderr)
        return 1

    try:
        w = WorkspaceClient()
    except Exception as exc:
        print(f"ERROR: WorkspaceClient(): {exc}", file=sys.stderr)
        return 1

    sp_id = (args.service_principal_id or "").strip()
    if not sp_id:
        app_name = (args.app_name or "").strip()
        if not app_name:
            print("ERROR: --app-name or --service-principal-id required", file=sys.stderr)
            return 2
        try:
            app = w.apps.get(app_name)
        except Exception as exc:
            print(f"ERROR: apps.get({app_name!r}): {exc}", file=sys.stderr)
            return 1
        sp_id = (getattr(app, "service_principal_client_id", None) or "").strip()
    if not sp_id:
        print("ERROR: could not resolve app service_principal_client_id", file=sys.stderr)
        return 1

    ok = True
    for name in endpoints:
        if not grant_can_query(w, endpoint_name=name, service_principal_id=sp_id):
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
