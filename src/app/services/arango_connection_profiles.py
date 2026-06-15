"""Persist named Arango connection profiles on the UC workflow-data volume."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from app.workflow_platform import workflow_data_volume as vol
from app.workflow_platform.runtime import workflow_config_dict
from app.workflow_platform.services.databricks_sql import execute_sql
from app.workflow_platform.services.registry_types import parse_fqn_table

log = logging.getLogger(__name__)

_PROFILES_REL = "settings/arango_connection_profiles.json"
_KUBECONFIG_DIR = "settings/kubeconfig"
_PASSWORD_PLACEHOLDER = "__UNCHANGED__"
_PROFILE_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_ENVIRONMENTS = frozenset({"aws", "gcs", "local"})

_TEMPLATE_DEFAULTS: dict[str, dict[str, Any]] = {
    "aws": {
        "display_name": "AWS",
        "environment": "aws",
        "cluster_name": "aws-arango",
        "username": "root",
        "password": "",
        "server_endpoint": "",
        "protocol": "https",
        "port": 443,
    },
    "gcs": {
        "display_name": "GCS",
        "environment": "gcs",
        "cluster_name": "gcs-arango",
        "username": "root",
        "password": "",
        "server_endpoint": "",
        "protocol": "https",
        "port": 443,
    },
    "local": {
        "display_name": "Local",
        "environment": "local",
        "cluster_name": "local-minikube-dev",
        "username": "root",
        "password": "",
        "server_endpoint": "",
        "protocol": "https",
        "port": None,
    },
}


def environments() -> tuple[str, ...]:
    return ("aws", "gcs", "local")


def parse_server_endpoint(endpoint: str) -> tuple[str, str, int]:
    """Parse a host or URL into ``(hostname, protocol, port)``."""
    raw = (endpoint or "").strip()
    if not raw:
        raise ValueError("server_endpoint is required")
    if "://" not in raw:
        raw = f"https://{raw}"
    parts = urlsplit(raw)
    host = (parts.hostname or "").strip()
    if not host:
        raise ValueError("server_endpoint must include a hostname")
    protocol = (parts.scheme or "https").strip().lower()
    if protocol not in {"http", "https"}:
        raise ValueError("protocol must be http or https")
    port = parts.port
    if port is None:
        port = 443 if protocol == "https" else 80
    if port < 1 or port > 65535:
        raise ValueError("port must be 1-65535")
    return host, protocol, int(port)


def parse_stored_port(value: Any) -> int | None:
    """Parse optional profile/registry port (empty → ``None``)."""
    if value is None or value == "":
        return None
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    if port < 1 or port > 65535:
        return None
    return port


def endpoint_has_explicit_port(server_endpoint: str) -> bool:
    raw = (server_endpoint or "").strip()
    if not raw:
        return False
    if "://" not in raw:
        raw = f"https://{raw}"
    return urlsplit(raw).port is not None


def _effective_server_endpoint(
    profile: dict[str, Any],
    overrides: dict[str, Any] | None = None,
) -> str:
    """Resolve hostname from test/save overrides or stored profile (legacy field names included)."""
    ov = overrides or {}
    ov_val = str(ov.get("server_endpoint") or "").strip()
    if ov_val:
        return ov_val
    for key in ("server_endpoint", "endpoint", "host", "ip_address"):
        val = str(profile.get(key) or "").strip()
        if val:
            return val
    return ""


def resolve_connection_target(
    server_endpoint: str,
    *,
    profile: dict[str, Any] | None = None,
    port: int | None = None,
) -> tuple[str, str, int]:
    """
    Resolve ``(host, protocol, port)`` for probes and ``arango_connection_registry``.

    Precedence when the endpoint URL has no ``:port``:
    1. Explicit ``port`` argument (form / test payload)
    2. ``port`` stored on the profile
    3. Default for scheme (443 https, 80 http)
    """
    endpoint = (server_endpoint or "").strip()
    if not endpoint:
        raise ValueError("server_endpoint is required")

    host, parsed_protocol, parsed_port = parse_server_endpoint(endpoint)
    protocol = str(parsed_protocol).lower()

    if endpoint_has_explicit_port(endpoint):
        return host, protocol, parsed_port

    explicit = parse_stored_port(port)
    if explicit is None and profile is not None:
        explicit = parse_stored_port(profile.get("port"))

    if explicit is not None:
        return host, protocol, explicit

    return host, protocol, parsed_port


def validate_profile_key(profile_key: str) -> str:
    key = (profile_key or "").strip().lower()
    if not _PROFILE_KEY_RE.match(key):
        raise ValueError(
            "profile_key must start with a letter and contain only lowercase letters, "
            "digits, hyphens, and underscores (max 64 chars)"
        )
    return key


def _slugify_profile_key(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", (name or "").strip().lower()).strip("-")
    slug = slug[:64]
    if not slug or not slug[0].isalpha():
        slug = f"conn-{slug}" if slug else "connection"
    return validate_profile_key(slug)


def _unique_profile_key(base: str, existing: set[str]) -> str:
    key = validate_profile_key(base)
    if key not in existing:
        return key
    n = 2
    while True:
        candidate = validate_profile_key(f"{key}-{n}")
        if candidate not in existing:
            return candidate
        n += 1


def _kubeconfig_rel(profile_key: str) -> str:
    return f"{_KUBECONFIG_DIR}/{profile_key}.yaml"


def _load_doc() -> dict[str, Any]:
    try:
        raw = vol.read_bytes(_PROFILES_REL)
        data = json.loads(raw.decode("utf-8"))
        return _normalize_doc(data if isinstance(data, dict) else {})
    except FileNotFoundError:
        return {"version": 2, "active_profile": "", "profiles": {}}
    except json.JSONDecodeError as exc:
        log.error("Invalid Arango connection profiles JSON: %s", exc)
        raise ValueError(
            "Connection profiles file is invalid JSON on the UC volume — "
            "check arango_workflow_volume/workflow-data/settings/arango_connection_profiles.json"
        ) from exc
    except OSError as exc:
        log.error("Cannot read Arango connection profiles from UC volume: %s", exc)
        raise ValueError(f"Cannot read connection profiles from UC volume: {exc}") from exc
    except UnicodeDecodeError as exc:
        log.error("Cannot decode Arango connection profiles: %s", exc)
        raise ValueError("Connection profiles file is not valid UTF-8 on the UC volume") from exc


def _normalize_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """Migrate legacy aws/gcs/local-only docs to version 2 named profiles."""
    version = int(doc.get("version") or 1)
    raw_profiles = doc.get("profiles") if isinstance(doc.get("profiles"), dict) else {}
    profiles: dict[str, dict[str, Any]] = {}

    for key, value in raw_profiles.items():
        if not isinstance(value, dict):
            continue
        try:
            slug = validate_profile_key(str(key))
        except ValueError:
            continue
        merged = dict(value)
        if not str(merged.get("display_name") or "").strip():
            merged["display_name"] = str(merged.get("cluster_name") or slug)
        env = str(merged.get("environment") or slug).strip().lower()
        if env not in _ENVIRONMENTS:
            env = "aws" if slug == "aws" else "gcs" if slug == "gcs" else "local" if slug == "local" else "aws"
        merged["environment"] = env
        profiles[slug] = merged

    active = str(doc.get("active_profile") or "").strip().lower()
    if active and active not in profiles:
        active = ""

    return {
        "version": 2 if version >= 2 else 2,
        "active_profile": active,
        "profiles": profiles,
    }


def _save_doc(doc: dict[str, Any]) -> None:
    vol.ensure_workflow_data_dirs()
    vol.write_bytes(
        relative_path=_PROFILES_REL,
        content=json.dumps(doc, indent=2).encode("utf-8"),
    )


def _is_profile_saved(profile: dict[str, Any]) -> bool:
    endpoint = str(profile.get("server_endpoint") or "").strip()
    password = str(profile.get("password") or "")
    return bool(endpoint) and bool(password)


def profile_display_name(profile_key: str, profile: dict[str, Any] | None) -> str:
    if not profile:
        return profile_key
    for field in ("display_name", "cluster_name"):
        value = str(profile.get(field) or "").strip()
        if value:
            return value
    return profile_key


def _public_profile(profile_key: str, profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_key": profile_key,
        "display_name": profile_display_name(profile_key, profile),
        "environment": str(profile.get("environment") or "aws"),
        "cluster_name": str(profile.get("cluster_name") or ""),
        "username": str(profile.get("username") or "root"),
        "password": "",
        "password_set": bool(str(profile.get("password") or "")),
        "server_endpoint": str(profile.get("server_endpoint") or ""),
        "protocol": str(profile.get("protocol") or "https"),
        "port": parse_stored_port(profile.get("port")),
        "kubeconfig_stored": bool(profile.get("kubeconfig_stored")),
        "kubeconfig_filename": str(profile.get("kubeconfig_filename") or ""),
        "saved": _is_profile_saved(profile),
    }


def load_connection_profiles() -> dict[str, Any]:
    """Return all profiles on the UC volume for the Connection UI (passwords never returned)."""
    doc = _load_doc()
    profiles_raw = doc.get("profiles") if isinstance(doc.get("profiles"), dict) else {}
    all_profiles = {
        key: _public_profile(key, profile)
        for key, profile in sorted(profiles_raw.items())
        if isinstance(profile, dict)
    }
    active = str(doc.get("active_profile") or "").strip().lower()
    if active not in profiles_raw:
        active = ""
    return {
        "version": int(doc.get("version") or 2),
        "active_profile": active,
        "profiles": all_profiles,
        "profile_keys": list(all_profiles.keys()),
        "saved_profile_keys": [key for key, profile in all_profiles.items() if profile.get("saved")],
        "templates": {
            env: {
                "environment": env,
                "display_name": _TEMPLATE_DEFAULTS[env]["display_name"],
                "cluster_name": _TEMPLATE_DEFAULTS[env]["cluster_name"],
                "server_endpoint": _TEMPLATE_DEFAULTS[env]["server_endpoint"],
                "protocol": _TEMPLATE_DEFAULTS[env]["protocol"],
                "port": _TEMPLATE_DEFAULTS[env]["port"],
            }
            for env in environments()
        },
        "storage_path": _PROFILES_REL,
        "kubeconfig_dir": _KUBECONFIG_DIR,
    }


def get_connection_ui_context() -> dict[str, Any]:
    """Summarize saved/active profiles for the home-page connection widget."""
    doc = _load_doc()
    profiles_raw = doc.get("profiles") if isinstance(doc.get("profiles"), dict) else {}
    saved_keys = [
        key
        for key, profile in profiles_raw.items()
        if isinstance(profile, dict) and _is_profile_saved(profile)
    ]
    active = str(doc.get("active_profile") or "").strip().lower()
    active_profile = profiles_raw.get(active) if active in profiles_raw else None
    if active and active not in saved_keys:
        active = ""
        active_profile = None
    return {
        "has_saved_profiles": bool(saved_keys),
        "saved_profile_count": len(saved_keys),
        "saved_profile_keys": saved_keys,
        "active_profile": active,
        "active_profile_display_name": profile_display_name(active, active_profile)
        if active_profile
        else "",
    }


def connection_ui_for_ready(*, probe_ok: bool, registry_ok: bool) -> dict[str, Any]:
    """Map connectivity probe results to user-facing connection status copy."""
    ctx = get_connection_ui_context()
    display = ctx.get("active_profile_display_name") or ""
    if probe_ok and registry_ok:
        return {
            **ctx,
            "ui_variant": "connected",
            "ui_message": display or "Connected",
        }
    if not ctx.get("has_saved_profiles"):
        return {
            **ctx,
            "ui_variant": "unset",
            "ui_message": "Click to Connect",
        }
    return {
        **ctx,
        "ui_variant": "failed",
        "ui_message": "Connection Failed",
    }


def create_connection_profile(
    *,
    display_name: str,
    environment: str = "aws",
    profile_key: str | None = None,
) -> dict[str, Any]:
    """Create a new empty profile shell (saved on first Save with credentials)."""
    env = (environment or "aws").strip().lower()
    if env not in _ENVIRONMENTS:
        raise ValueError(f"environment must be one of: {', '.join(environments())}")

    doc = _load_doc()
    profiles = doc.get("profiles") if isinstance(doc.get("profiles"), dict) else {}
    existing = set(profiles.keys())

    name = (display_name or _TEMPLATE_DEFAULTS[env]["display_name"]).strip()
    if profile_key:
        key = validate_profile_key(profile_key)
        if key in existing:
            raise ValueError(f"profile_key already exists: {key}")
    else:
        base = _slugify_profile_key(name)
        key = _unique_profile_key(base, existing)

    template = dict(_TEMPLATE_DEFAULTS[env])
    profiles[key] = {
        **template,
        "display_name": name,
        "environment": env,
        "username": "root",
        "password": "",
        "server_endpoint": "",
    }
    doc["version"] = 2
    doc["profiles"] = profiles
    if not doc.get("active_profile"):
        doc["active_profile"] = key
    _save_doc(doc)
    return {"ok": True, "profile_key": key, "profile": _public_profile(key, profiles[key])}


def _require_existing_profile(doc: dict[str, Any], profile_key: str) -> tuple[str, dict[str, Any]]:
    key = validate_profile_key(profile_key)
    profiles = doc.get("profiles") if isinstance(doc.get("profiles"), dict) else {}
    profile = profiles.get(key)
    if not isinstance(profile, dict):
        raise ValueError(f"Unknown profile: {key}")
    return key, profile


def save_connection_profile(profile_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Merge and persist one profile. Empty password keeps the existing secret."""
    doc = _load_doc()
    profiles = doc.get("profiles") if isinstance(doc.get("profiles"), dict) else {}

    key = validate_profile_key(profile_key)
    if key not in profiles:
        env = str(payload.get("environment") or "aws").strip().lower()
        if env not in _ENVIRONMENTS:
            env = "aws"
        profiles[key] = dict(_TEMPLATE_DEFAULTS[env])
        profiles[key]["display_name"] = str(payload.get("display_name") or key)

    current = profiles[key]

    display_name = str(
        payload.get("display_name", current.get("display_name", key)) or key
    ).strip()
    username = str(payload.get("username", current.get("username", "root")) or "root").strip()
    password_in = payload.get("password")
    if password_in is None or str(password_in) == _PASSWORD_PLACEHOLDER:
        password = str(current.get("password") or "")
    elif str(password_in).strip():
        password = str(password_in)
    else:
        password = str(current.get("password") or "")

    if not password:
        raise ValueError(
            "password is required — enter the Arango root password on the Connection page"
        )

    server_endpoint = str(
        payload.get("server_endpoint", current.get("server_endpoint", "")) or ""
    ).strip()
    if not server_endpoint:
        server_endpoint = _effective_server_endpoint(current, None)
    if not server_endpoint:
        raise ValueError(
            "server_endpoint is required — enter the Arango hostname "
            "(e.g. gg8dcifd.rnd.pilot.arango.ai) in Server endpoint"
        )
    cluster_name = str(
        payload.get("cluster_name", current.get("cluster_name", key)) or key
    ).strip()

    env = str(payload.get("environment", current.get("environment", "aws")) or "aws").lower()
    if env not in _ENVIRONMENTS:
        env = str(current.get("environment") or "aws")

    if "port" in payload:
        stored_port = parse_stored_port(payload.get("port"))
    else:
        stored_port = parse_stored_port(current.get("port"))

    protocol = str(payload.get("protocol", current.get("protocol", "https")) or "https").lower()
    if server_endpoint:
        host, protocol, _resolved_port = resolve_connection_target(
            server_endpoint,
            profile=current,
            port=stored_port if "port" in payload else parse_stored_port(current.get("port")),
        )
        server_endpoint = host

    profiles[key] = {
        **current,
        "display_name": display_name,
        "environment": env,
        "cluster_name": cluster_name,
        "username": username,
        "password": password,
        "server_endpoint": server_endpoint,
        "protocol": protocol,
        "port": stored_port,
    }

    doc["version"] = 2
    doc["profiles"] = profiles
    if not doc.get("active_profile"):
        doc["active_profile"] = key
    _save_doc(doc)
    return {"ok": True, "profile_key": key, "profile": _public_profile(key, profiles[key])}


def get_active_profile_auth() -> tuple[str | None, str | None]:
    """Return basic-auth credentials for the active profile, if configured."""
    doc = _load_doc()
    active = str(doc.get("active_profile") or "").strip().lower()
    profiles = doc.get("profiles") if isinstance(doc.get("profiles"), dict) else {}
    profile = profiles.get(active)
    if not isinstance(profile, dict):
        return None, None
    user = str(profile.get("username") or "").strip()
    password = profile.get("password")
    if user:
        return user, str(password) if password is not None else ""
    return None, None


def upsert_registry_for_profile(profile_key: str) -> dict[str, Any]:
    """Mark profile active and upsert the UC Arango connection registry row."""
    doc = _load_doc()
    profiles = doc.get("profiles") if isinstance(doc.get("profiles"), dict) else {}
    key, profile = _require_existing_profile(doc, profile_key)

    endpoint = str(profile.get("server_endpoint") or "").strip()
    if not endpoint:
        raise ValueError("server_endpoint is required before connecting")

    host, protocol, port = resolve_connection_target(endpoint, profile=profile)
    cluster_name = str(profile.get("cluster_name") or profile_display_name(key, profile)).strip()
    username = str(profile.get("username") or "root").strip()
    password = str(profile.get("password") or "")
    if not username:
        raise ValueError("username is required before connecting")
    if not password:
        raise ValueError(
            "password is required before connecting — enter it on the Connection page and Save first"
        )

    from app.workflow_platform.deployment_profile import should_upsert_connection_registry_on_connect

    cfg = workflow_config_dict()
    table_name = (cfg.get("ARANGO_REGISTRY_TABLE") or "").strip()
    warehouse_id = (cfg.get("DATABRICKS_SQL_WAREHOUSE_ID") or "").strip()

    if should_upsert_connection_registry_on_connect():
        if not table_name or not warehouse_id:
            raise ValueError("ARANGO_REGISTRY_TABLE and DATABRICKS_SQL_WAREHOUSE_ID are required")

        _upsert_registry_entry(
            table_name=table_name,
            warehouse_id=warehouse_id,
            cluster_name=cluster_name,
            ip_address=host,
            port=port,
            protocol=protocol,
        )

    profiles[key]["server_endpoint"] = host
    profiles[key]["protocol"] = protocol
    profiles[key]["port"] = port
    doc["profiles"] = profiles
    doc["active_profile"] = key
    doc["version"] = 2
    _save_doc(doc)

    return {
        "ok": True,
        "active_profile": key,
        "active_profile_display_name": profile_display_name(key, profiles[key]),
        "registry": {
            "cluster_name": cluster_name,
            "ip_address": host,
            "port": port,
            "protocol": protocol,
            "table": table_name,
        },
    }


def test_profile_connection(profile_key: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Probe Arango ``/_api/version`` using saved or supplied credentials."""
    from app.services.arango_connectivity import ping_arango_endpoint

    doc = _load_doc()
    key, profile = _require_existing_profile(doc, profile_key)
    overrides = payload or {}

    endpoint = _effective_server_endpoint(profile, overrides)
    if not endpoint:
        raise ValueError(
            "server_endpoint is required to test connection — enter the Arango hostname "
            "in Server endpoint, then Save or Test again"
        )

    port_override = parse_stored_port(overrides.get("port")) if "port" in overrides else None
    host, protocol, port = resolve_connection_target(
        endpoint,
        profile=profile,
        port=port_override,
    )
    username = str(overrides.get("username") or profile.get("username") or "root").strip()
    password_in = overrides.get("password")
    if password_in is None or str(password_in) == _PASSWORD_PLACEHOLDER:
        password = str(profile.get("password") or "")
    elif str(password_in).strip():
        password = str(password_in)
    else:
        password = str(profile.get("password") or "")

    verify_tls = str(overrides.get("verify_tls", "true")).strip().lower() != "false"
    timeout = float(overrides.get("timeout_seconds") or 5.0)

    probe = ping_arango_endpoint(
        protocol=protocol,
        ip_address=host,
        port=port,
        timeout_seconds=timeout,
        basic_auth_user=username or None,
        basic_auth_password=password if username else None,
        verify_tls=verify_tls,
    )
    return {
        "ok": bool(probe.get("reachable")),
        "profile": key,
        "profile_display_name": profile_display_name(key, profile),
        "endpoint": {
            "host": host,
            "protocol": protocol,
            "port": port,
            "username": username,
        },
        "probe": probe,
    }


def verify_gateway_arango_ping(*, timeout_seconds: float = 20.0) -> dict[str, Any]:
    """
    Probe Arango through arango-gateway-app (same path as extraction / MCP).

    Uses M2M Bearer to ``POST /api/arango/ping``; gateway reads UC profile + registry row.
    """
    import httpx

    from app.workflow_platform.databricks_outbound_auth import outbound_databricks_auth_headers
    from app.workflow_platform.runtime import workflow_config_dict
    from app.workflow_platform.services.gateway_url_registry import effective_gateway_base_url

    cfg = workflow_config_dict()
    base = effective_gateway_base_url(cfg).strip().rstrip("/")
    if not base:
        return {
            "ok": False,
            "error": (
                "Gateway URL is not configured. Deploy arango-gateway-app and publish to "
                "ARANGO_GATEWAY_REGISTRY_TABLE."
            ),
        }

    url = f"{base}/api/arango/ping"
    headers = outbound_databricks_auth_headers(peer_url=base) or None
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(url, json={}, headers=headers)
    except httpx.HTTPError as exc:
        return {"ok": False, "gateway_url": base, "error": str(exc)}

    body: dict[str, Any] = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            body = parsed
    except Exception:
        body = {"raw": (response.text or "")[:500]}

    reachable = response.is_success and str(body.get("status", "")).lower() in {
        "ok",
        "success",
    }
    if not reachable and response.is_success:
        probe = body.get("probe") if isinstance(body.get("probe"), dict) else {}
        reachable = bool(probe.get("reachable"))

    if reachable:
        return {"ok": True, "gateway_url": base, "status_code": response.status_code, "body": body}

    err = str(body.get("error") or body.get("message") or response.reason_phrase or "gateway ping failed")
    if response.status_code == 401:
        err = (
            f"{err} — workflow app service principal may lack CAN_USE on arango-gateway-app "
            "(run grant_peer_app_can_use.py via deploy_app.sh)."
        )
    return {
        "ok": False,
        "gateway_url": base,
        "status_code": response.status_code,
        "error": err,
        "body": body,
    }


def save_kubeconfig(profile_key: str, *, filename: str, content: bytes) -> dict[str, Any]:
    """Store kubeconfig YAML for a profile on the UC workflow-data volume."""
    doc = _load_doc()
    key, profile = _require_existing_profile(doc, profile_key)
    if not content:
        raise ValueError("kubeconfig file is empty")
    if len(content) > 512_000:
        raise ValueError("kubeconfig file exceeds 512KB limit")

    rel = _kubeconfig_rel(key)
    vol.ensure_workflow_data_dirs()
    vol.write_bytes(relative_path=rel, content=content)

    profiles = doc.get("profiles") if isinstance(doc.get("profiles"), dict) else {}
    profiles[key] = {**profile, "kubeconfig_stored": True, "kubeconfig_filename": (filename or f"{key}-kubeconfig.yaml").strip()}
    doc["profiles"] = profiles
    doc["version"] = 2
    _save_doc(doc)

    return {
        "ok": True,
        "profile": key,
        "kubeconfig_path": rel,
        "kubeconfig_filename": profiles[key]["kubeconfig_filename"],
    }


def _upsert_registry_entry(
    *,
    table_name: str,
    warehouse_id: str,
    cluster_name: str,
    ip_address: str,
    port: int,
    protocol: str,
) -> None:
    ref = parse_fqn_table(table_name)
    execute_sql(
        statement=f"UPDATE {ref.fqn} SET is_active = FALSE WHERE is_active = TRUE",
        warehouse_id=warehouse_id,
    )
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    safe_cluster = cluster_name.replace("'", "''")
    safe_ip = ip_address.replace("'", "''")
    safe_protocol = protocol.replace("'", "''")
    execute_sql(
        statement=f"""
            INSERT INTO {ref.fqn}
                (cluster_name, ip_address, port, protocol, is_active, updated_at)
            VALUES
                ('{safe_cluster}', '{safe_ip}', {int(port)}, '{safe_protocol}', TRUE, TIMESTAMP '{ts}')
        """,
        warehouse_id=warehouse_id,
    )
