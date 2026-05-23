"""Unity Catalog table discovery and comment/annotation updates."""

from __future__ import annotations

import logging
import re
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import ColumnInfo, TableInfo

from app.workflow_platform.config import AppConfig
from app.workflow_platform.services.databricks_sql import execute_sql

log = logging.getLogger(__name__)

_DEFAULT_MAX_TABLES = 10_000


def _workspace() -> WorkspaceClient:
    return WorkspaceClient()


def _enum_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _sql_string_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _quote_column_ident(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def _parse_full_name(full_name: str) -> tuple[str, str, str]:
    parts = [p.strip() for p in full_name.split(".") if p.strip()]
    if len(parts) != 3:
        raise ValueError(f"Expected catalog.schema.table, got {full_name!r}")
    return parts[0], parts[1], parts[2]


def list_uc_tables(
    *,
    search: str | None = None,
    max_tables: int = _DEFAULT_MAX_TABLES,
) -> dict[str, Any]:
    """List accessible UC tables (lightweight; columns omitted)."""
    w = _workspace()
    rows: list[dict[str, Any]] = []
    needle = (search or "").strip().lower()
    count = 0

    for cat in w.catalogs.list(max_results=0):
        cname = cat.name
        if not cname:
            continue
        for sch in w.schemas.list(catalog_name=cname, max_results=0):
            sname = sch.name
            if not sname:
                continue
            for tbl in w.tables.list(
                catalog_name=cname,
                schema_name=sname,
                max_results=0,
                omit_columns=True,
                omit_properties=False,
            ):
                if count >= max_tables:
                    break
                tname = tbl.name
                if not tname:
                    continue
                full_name = tbl.full_name or f"{cname}.{sname}.{tname}"
                if needle and needle not in full_name.lower():
                    continue
                rows.append(
                    {
                        "table_id": tbl.table_id,
                        "full_name": full_name,
                        "catalog": cname,
                        "schema": sname,
                        "name": tname,
                        "table_type": _enum_str(tbl.table_type),
                        "comment": tbl.comment or "",
                    }
                )
                count += 1
            if count >= max_tables:
                break
        if count >= max_tables:
            break

    rows.sort(key=lambda r: r["full_name"].lower())
    return {
        "status": "ok",
        "table_count": len(rows),
        "tables": rows,
    }


def _serialize_column(col: ColumnInfo) -> dict[str, Any]:
    return {
        "name": col.name or "",
        "type_text": col.type_text or "",
        "type_name": _enum_str(col.type_name),
        "nullable": col.nullable,
        "comment": col.comment or "",
        "position": col.position,
    }


def get_uc_table_detail(full_name: str) -> dict[str, Any]:
    """Return table comment and column metadata for one UC table."""
    full_name = full_name.strip()
    _parse_full_name(full_name)
    w = _workspace()
    tbl: TableInfo = w.tables.get(full_name)
    columns = [_serialize_column(c) for c in (tbl.columns or [])]
    columns.sort(key=lambda c: (c.get("position") is None, c.get("position") or 0, c["name"]))
    return {
        "status": "ok",
        "full_name": full_name,
        "table_id": tbl.table_id,
        "table_type": _enum_str(tbl.table_type),
        "data_source_format": _enum_str(tbl.data_source_format),
        "owner": tbl.owner,
        "table_comment": tbl.comment or "",
        "columns": columns,
    }


def save_uc_table_annotations(
    full_name: str,
    *,
    table_comment: str,
    columns: list[dict[str, Any]],
) -> dict[str, Any]:
    """Push table and column comments to Unity Catalog via SQL DDL."""
    full_name = full_name.strip()
    _parse_full_name(full_name)
    if not re.match(r"^[\w.]+$", full_name):
        raise ValueError("Invalid table name")

    warehouse_id = (AppConfig().DATABRICKS_SQL_WAREHOUSE_ID or "").strip()
    if not warehouse_id:
        raise RuntimeError("DATABRICKS_SQL_WAREHOUSE_ID is not configured")

    statements: list[str] = []
    table_comment = table_comment if table_comment is not None else ""
    if table_comment.strip():
        statements.append(
            f"COMMENT ON TABLE {full_name} IS {_sql_string_literal(table_comment.strip())}"
        )
    else:
        statements.append(f"COMMENT ON TABLE {full_name} IS NULL")

    for col in columns:
        name = (col.get("name") or "").strip()
        if not name:
            continue
        comment = col.get("comment")
        if comment is None:
            continue
        comment_str = str(comment).strip()
        col_ident = _quote_column_ident(name)
        if comment_str:
            statements.append(
                f"ALTER TABLE {full_name} ALTER COLUMN {col_ident} "
                f"COMMENT {_sql_string_literal(comment_str)}"
            )
        else:
            statements.append(
                f"ALTER TABLE {full_name} ALTER COLUMN {col_ident} COMMENT ''"
            )

    for stmt in statements:
        log.info("uc_catalog annotation SQL: %s", stmt[:200])
        execute_sql(stmt, warehouse_id)

    return {
        "status": "ok",
        "full_name": full_name,
        "statements_executed": len(statements),
    }
