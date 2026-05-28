#!/usr/bin/env python3
"""Query UC registry Delta tables (gateway, agent, Arango connection) via SQL warehouse."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from app.workflow_platform.runtime import workflow_config_dict
from app.workflow_platform.services.databricks_sql import execute_sql
from app.workflow_platform.services.registry_types import parse_fqn_table


def _query(label: str, fqn: str, sql: str, wid: str) -> None:
    print(f"=== {label} ({fqn}) ===")
    try:
        ref = parse_fqn_table(fqn)
        result = execute_sql(sql.format(fqn=ref.fqn), wid)
        rows = result.get("rows") or []
        if not rows:
            print("(no rows)")
        else:
            print(json.dumps(rows, indent=2, default=str))
    except Exception as exc:
        print(f"(error: {exc})")
    print()


def main() -> int:
    cfg = workflow_config_dict()
    wid = (cfg.get("DATABRICKS_SQL_WAREHOUSE_ID") or "").strip()
    if not wid:
        print("ERROR: set DATABRICKS_SQL_WAREHOUSE_ID", file=sys.stderr)
        return 1

    gw = cfg.get("ARANGO_GATEWAY_REGISTRY_TABLE") or ""
    ag = cfg.get("ARANGO_AGENT_REGISTRY_TABLE") or ""
    wf = cfg.get("ARANGO_WORKFLOW_REGISTRY_TABLE") or ""
    conn = cfg.get("ARANGO_REGISTRY_TABLE") or ""

    _query(
        "Gateway app URL (active)",
        gw,
        "SELECT base_url, app_name, is_active, updated_at FROM {fqn} "
        "WHERE is_active IS TRUE ORDER BY updated_at DESC LIMIT 5",
        wid,
    )
    _query(
        "MCP agent app URL (active)",
        ag,
        "SELECT base_url, app_name, is_active, updated_at FROM {fqn} "
        "WHERE is_active IS TRUE ORDER BY updated_at DESC LIMIT 5",
        wid,
    )
    _query(
        "Workflow app URL (active)",
        wf,
        "SELECT base_url, app_name, is_active, updated_at FROM {fqn} "
        "WHERE is_active IS TRUE ORDER BY updated_at DESC LIMIT 5",
        wid,
    )
    _query(
        "Arango connection (active)",
        conn,
        "SELECT cluster_name, ip_address, port, protocol, is_active, updated_at "
        "FROM {fqn} WHERE is_active IS TRUE ORDER BY updated_at DESC LIMIT 3",
        wid,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
