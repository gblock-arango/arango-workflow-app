#!/usr/bin/env python3
"""Print effective peer-app URLs (same resolution as the deployed workflow BFF).

Requires DATABRICKS_SQL_WAREHOUSE_ID (and optional ARANGO_*_BASE_URL overrides).
Run from repo root: PYTHONPATH=src python scripts/print_effective_peer_urls.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from app.workflow_platform.runtime import workflow_config_dict
from app.workflow_platform.services.agent_url_registry import effective_arango_agent_base_url
from app.workflow_platform.services.bronze_injector_uc_registry import effective_injector_uc_snapshot
from app.workflow_platform.services.gateway_url_registry import (
    effective_gateway_base_url,
    effective_gateway_iframe_base_url,
)
from app.workflow_platform.services.workflow_url_registry import effective_workflow_base_url


def main() -> int:
    cfg = workflow_config_dict()
    wid = (cfg.get("DATABRICKS_SQL_WAREHOUSE_ID") or "").strip()
    if not wid:
        print("ERROR: DATABRICKS_SQL_WAREHOUSE_ID is not set.", file=sys.stderr)
        return 1

    out = {
        "DATABRICKS_SQL_WAREHOUSE_ID": wid,
        "ARANGO_GATEWAY_REGISTRY_TABLE": cfg.get("ARANGO_GATEWAY_REGISTRY_TABLE"),
        "ARANGO_AGENT_REGISTRY_TABLE": cfg.get("ARANGO_AGENT_REGISTRY_TABLE"),
        "ARANGO_WORKFLOW_REGISTRY_TABLE": cfg.get("ARANGO_WORKFLOW_REGISTRY_TABLE"),
        "ARANGO_REGISTRY_TABLE": cfg.get("ARANGO_REGISTRY_TABLE"),
        "gateway_base_url": effective_gateway_base_url(cfg) or None,
        "gateway_iframe_base_url": effective_gateway_iframe_base_url(cfg) or None,
        "arango_agent_base_url": effective_arango_agent_base_url(cfg) or None,
        "workflow_base_url": effective_workflow_base_url(cfg) or None,
        "bronze_injector": effective_injector_uc_snapshot(cfg),
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
