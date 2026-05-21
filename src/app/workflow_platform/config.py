"""Runtime config for the arango-workflow-app Databricks App (UC peer URLs + BFF)."""

import os
from dataclasses import dataclass, field

_DEFAULT_ARANGO_REGISTRY_TABLE = "workspace.default.arango_connection_registry"
_DEFAULT_ARANGO_GATEWAY_REGISTRY_TABLE = "workspace.default.arango_gateway_registry"
_DEFAULT_ARANGO_AGENT_REGISTRY_TABLE = "workspace.default.arango_agent_registry"
_DEFAULT_ARANGO_WORKFLOW_REGISTRY_TABLE = "workspace.default.arango_workflow_registry"
_DEFAULT_ARANGO_BRONZE_SIMULATED_INJECTOR_REGISTRY_TABLE = (
    "workspace.default.arango_bronze_simulated_injector_registry"
)


def _uc_graph_volume_name_from_env() -> str:
    v = (os.environ.get("UC_GRAPH_VOLUME_NAME") or "arango_agent_volume").strip()
    return v if v else "arango_agent_volume"


def _uc_graph_snapshot_base() -> str:
    if "UC_GRAPH_SNAPSHOT_BASE" in os.environ:
        return os.environ.get("UC_GRAPH_SNAPSHOT_BASE", "").strip()
    table = (
        (os.environ.get("ARANGO_REGISTRY_TABLE", "") or "").strip()
        or _DEFAULT_ARANGO_REGISTRY_TABLE
    )
    parts = table.split(".")
    if len(parts) >= 3:
        catalog, schema = parts[0], parts[1]
        vol = _uc_graph_volume_name_from_env()
        return f"/Volumes/{catalog}/{schema}/{vol}/uc_graph_snapshots"
    return ""


@dataclass
class AppConfig:
    """Workflow shell: OntoExtract UI/API + BFF; Arango via gateway UC; Genie proxied to mcp-arango-agent."""

    DATABRICKS_SQL_WAREHOUSE_ID: str = field(
        default_factory=lambda: (os.environ.get("DATABRICKS_SQL_WAREHOUSE_ID", "") or "").strip()
    )
    ARANGO_GATEWAY_BASE_URL: str = field(
        default_factory=lambda: (os.environ.get("ARANGO_GATEWAY_BASE_URL", "") or "").strip()
    )
    ARANGO_GATEWAY_REGISTRY_TABLE: str = field(
        default_factory=lambda: (
            (os.environ.get("ARANGO_GATEWAY_REGISTRY_TABLE", "") or "").strip()
            or _DEFAULT_ARANGO_GATEWAY_REGISTRY_TABLE
        )
    )
    ARANGO_REGISTRY_TABLE: str = field(
        default_factory=lambda: (
            (os.environ.get("ARANGO_REGISTRY_TABLE", "") or "").strip()
            or _DEFAULT_ARANGO_REGISTRY_TABLE
        )
    )
    UC_GRAPH_VOLUME_NAME: str = field(
        default_factory=_uc_graph_volume_name_from_env
    )
    UC_GRAPH_SNAPSHOT_BASE: str = field(
        default_factory=_uc_graph_snapshot_base
    )
    UC_WORKFLOW_DATA_SUBDIR: str = field(
        default_factory=lambda: (
            (os.environ.get("UC_WORKFLOW_DATA_SUBDIR", "") or "").strip()
            or "workflow-data"
        )
    )
    WORKFLOW_DATA_SEED_ON_STARTUP: str = field(
        default_factory=lambda: (os.environ.get("WORKFLOW_DATA_SEED_ON_STARTUP", "true") or "true")
    )
    DEBUG_STARTUP_CHECKS: bool = field(
        default_factory=lambda: os.environ.get("DEBUG_STARTUP_CHECKS", "false").lower()
        == "true"
    )
    DEBUG_WEBHOOK_URL: str = field(
        default_factory=lambda: os.environ.get("DEBUG_WEBHOOK_URL", "")
    )
    ARANGO_AGENT_BASE_URL: str = field(
        default_factory=lambda: (os.environ.get("ARANGO_AGENT_BASE_URL", "") or "").strip().rstrip("/")
    )
    ARANGO_AGENT_REGISTRY_TABLE: str = field(
        default_factory=lambda: (
            (os.environ.get("ARANGO_AGENT_REGISTRY_TABLE", "") or "").strip()
            or _DEFAULT_ARANGO_AGENT_REGISTRY_TABLE
        )
    )
    ARANGO_WORKFLOW_APP_BASE_URL: str = field(
        default_factory=lambda: (
            (os.environ.get("ARANGO_WORKFLOW_APP_BASE_URL", "") or "").strip().rstrip("/")
        )
    )
    ARANGO_WORKFLOW_REGISTRY_TABLE: str = field(
        default_factory=lambda: (
            (os.environ.get("ARANGO_WORKFLOW_REGISTRY_TABLE", "") or "").strip()
            or _DEFAULT_ARANGO_WORKFLOW_REGISTRY_TABLE
        )
    )
    ARANGO_WORKFLOW_REGISTRY_AUTO_CREATE: str = field(
        default_factory=lambda: (os.environ.get("ARANGO_WORKFLOW_REGISTRY_AUTO_CREATE", "true") or "true")
    )
    BRONZE_INJECTOR_BASE_URL: str = field(
        default_factory=lambda: (os.environ.get("BRONZE_INJECTOR_BASE_URL", "") or "").strip().rstrip(
            "/"
        )
    )
    ARANGO_BRONZE_SIMULATED_INJECTOR_REGISTRY_TABLE: str = field(
        default_factory=lambda: (
            (os.environ.get("ARANGO_BRONZE_SIMULATED_INJECTOR_REGISTRY_TABLE", "") or "").strip()
            or _DEFAULT_ARANGO_BRONZE_SIMULATED_INJECTOR_REGISTRY_TABLE
        )
    )
