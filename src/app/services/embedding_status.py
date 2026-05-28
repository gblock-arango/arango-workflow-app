"""Unity Catalog table for document embedding pipeline status (no Arango)."""

from __future__ import annotations

import logging
import os
from typing import Any

from app.workflow_platform.config import AppConfig
from app.workflow_platform.services.databricks_sql import execute_sql
from app.workflow_platform.services.registry_types import parse_fqn_table

log = logging.getLogger(__name__)

_DEFAULT_TABLE = "workspace.default.embedding_status"

_ACTIVE_STATUSES = frozenset({"parsing", "chunking", "embedding", "uploading"})

_table_ensured = False


def _sql_bool(value: Any) -> bool:
    """Parse UC/SQL boolean values (avoid ``bool('false')`` → True)."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    s = str(value).strip().lower()
    if s in ("false", "0", "no", "off", "", "null"):
        return False
    if s in ("true", "1", "yes", "t"):
        return True
    return bool(value)


def embedding_status_table_name() -> str:
    return (
        os.environ.get("EMBEDDING_STATUS_TABLE", "").strip() or _DEFAULT_TABLE
    )


def _warehouse_id() -> str:
    wid = (AppConfig().DATABRICKS_SQL_WAREHOUSE_ID or "").strip()
    if not wid:
        raise RuntimeError(
            "DATABRICKS_SQL_WAREHOUSE_ID is required for embedding_status UC table access"
        )
    return wid


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _row_from_sql(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_id": str(row.get("doc_id") or ""),
        "filename": str(row.get("filename") or ""),
        "mime_type": str(row.get("mime_type") or ""),
        "volume_relative_path": str(row.get("volume_relative_path") or ""),
        "file_size_bytes": int(row.get("file_size_bytes") or 0),
        "file_hash": str(row.get("file_hash") or ""),
        "status": str(row.get("status") or "staged"),
        "parsed": _sql_bool(row.get("parsed")),
        "chunked": _sql_bool(row.get("chunked")),
        "embedded": _sql_bool(row.get("embedded")),
        "chunk_count": int(row.get("chunk_count") or 0),
        "error_message": row.get("error_message"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def ensure_embedding_status_table() -> None:
    """Create Delta table if missing (idempotent; once per process)."""
    global _table_ensured
    if _table_ensured:
        return
    ref = parse_fqn_table(embedding_status_table_name())
    warehouse = _warehouse_id()
    execute_sql(
        statement=f"CREATE SCHEMA IF NOT EXISTS `{ref.catalog}`.`{ref.schema}`",
        warehouse_id=warehouse,
    )
    execute_sql(
        statement=f"""
            CREATE TABLE IF NOT EXISTS {ref.fqn} (
                doc_id STRING NOT NULL,
                filename STRING NOT NULL,
                mime_type STRING,
                volume_relative_path STRING NOT NULL,
                file_size_bytes BIGINT,
                file_hash STRING,
                status STRING NOT NULL,
                parsed BOOLEAN NOT NULL,
                chunked BOOLEAN NOT NULL,
                embedded BOOLEAN NOT NULL,
                chunk_count INT NOT NULL,
                error_message STRING,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            USING DELTA
        """,
        warehouse_id=warehouse,
    )
    try:
        execute_sql(
            statement=f"GRANT SELECT, MODIFY ON TABLE {ref.fqn} TO `account users`",
            warehouse_id=warehouse,
        )
    except Exception as exc:
        log.info("Could not GRANT embedding_status to account users: %s", exc)
    _table_ensured = True


def register_staged_document(
    *,
    doc_id: str,
    filename: str,
    mime_type: str,
    volume_relative_path: str,
    file_size_bytes: int,
    file_hash: str,
    status: str = "staged",
) -> dict[str, Any]:
    """Insert or replace a staged upload row."""
    ensure_embedding_status_table()
    ref = parse_fqn_table(embedding_status_table_name())
    warehouse = _warehouse_id()
    merge_sql = f"""
        MERGE INTO {ref.fqn} AS t
        USING (
            SELECT
                {_sql_str(doc_id)} AS doc_id,
                {_sql_str(filename)} AS filename,
                {_sql_str(mime_type)} AS mime_type,
                {_sql_str(volume_relative_path)} AS volume_relative_path,
                {int(file_size_bytes)} AS file_size_bytes,
                {_sql_str(file_hash)} AS file_hash,
                {_sql_str(status)} AS status,
                FALSE AS parsed,
                FALSE AS chunked,
                FALSE AS embedded,
                0 AS chunk_count,
                CAST(NULL AS STRING) AS error_message,
                current_timestamp() AS created_at,
                current_timestamp() AS updated_at
        ) AS s
        ON t.doc_id = s.doc_id
        WHEN MATCHED THEN UPDATE SET
            filename = s.filename,
            mime_type = s.mime_type,
            volume_relative_path = s.volume_relative_path,
            file_size_bytes = s.file_size_bytes,
            file_hash = s.file_hash,
            status = s.status,
            parsed = s.parsed,
            chunked = s.chunked,
            embedded = s.embedded,
            chunk_count = s.chunk_count,
            error_message = s.error_message,
            updated_at = s.updated_at
        WHEN NOT MATCHED THEN INSERT (
            doc_id, filename, mime_type, volume_relative_path, file_size_bytes,
            file_hash, status, parsed, chunked, embedded, chunk_count,
            error_message, created_at, updated_at
        ) VALUES (
            s.doc_id, s.filename, s.mime_type, s.volume_relative_path, s.file_size_bytes,
            s.file_hash, s.status, s.parsed, s.chunked, s.embedded, s.chunk_count,
            s.error_message, s.created_at, s.updated_at
        )
    """
    execute_sql(statement=merge_sql, warehouse_id=warehouse)
    row = get_embedding_status(doc_id)
    return row or _row_from_sql(
        {
            "doc_id": doc_id,
            "filename": filename,
            "mime_type": mime_type,
            "volume_relative_path": volume_relative_path,
            "file_size_bytes": file_size_bytes,
            "file_hash": file_hash,
            "status": status,
            "parsed": False,
            "chunked": False,
            "embedded": False,
            "chunk_count": 0,
        }
    )


def update_embedding_status(
    doc_id: str,
    *,
    status: str | None = None,
    parsed: bool | None = None,
    chunked: bool | None = None,
    embedded: bool | None = None,
    chunk_count: int | None = None,
    error_message: str | None = None,
    clear_error: bool = False,
) -> None:
    """Patch pipeline fields for one document."""
    ensure_embedding_status_table()
    ref = parse_fqn_table(embedding_status_table_name())
    warehouse = _warehouse_id()
    sets: list[str] = ["updated_at = current_timestamp()"]
    if status is not None:
        sets.append(f"status = {_sql_str(status)}")
    if parsed is not None:
        sets.append(f"parsed = {'TRUE' if parsed else 'FALSE'}")
    if chunked is not None:
        sets.append(f"chunked = {'TRUE' if chunked else 'FALSE'}")
    if embedded is not None:
        sets.append(f"embedded = {'TRUE' if embedded else 'FALSE'}")
    if chunk_count is not None:
        sets.append(f"chunk_count = {int(chunk_count)}")
    if clear_error:
        sets.append("error_message = NULL")
    elif error_message is not None:
        sets.append(f"error_message = {_sql_str(error_message)}")
    stmt = f"""
        UPDATE {ref.fqn}
        SET {", ".join(sets)}
        WHERE doc_id = {_sql_str(doc_id)}
    """
    execute_sql(statement=stmt, warehouse_id=warehouse)


def delete_embedding_status(doc_id: str) -> None:
    ref = parse_fqn_table(embedding_status_table_name())
    warehouse = _warehouse_id()
    execute_sql(
        statement=f"DELETE FROM {ref.fqn} WHERE doc_id = {_sql_str(doc_id)}",
        warehouse_id=warehouse,
    )


def find_by_file_hash(file_hash: str) -> dict[str, Any] | None:
    ensure_embedding_status_table()
    ref = parse_fqn_table(embedding_status_table_name())
    warehouse = _warehouse_id()
    result = execute_sql(
        statement=f"""
            SELECT * FROM {ref.fqn}
            WHERE file_hash = {_sql_str(file_hash)}
            ORDER BY updated_at DESC
            LIMIT 1
        """,
        warehouse_id=warehouse,
    )
    rows = result.get("rows") or []
    return _row_from_sql(rows[0]) if rows else None


def get_embedding_status(doc_id: str) -> dict[str, Any] | None:
    ensure_embedding_status_table()
    ref = parse_fqn_table(embedding_status_table_name())
    warehouse = _warehouse_id()
    result = execute_sql(
        statement=f"""
            SELECT * FROM {ref.fqn}
            WHERE doc_id = {_sql_str(doc_id)}
            LIMIT 1
        """,
        warehouse_id=warehouse,
    )
    rows = result.get("rows") or []
    return _row_from_sql(rows[0]) if rows else None


def list_embedding_status(*, limit: int = 500) -> list[dict[str, Any]]:
    ensure_embedding_status_table()
    ref = parse_fqn_table(embedding_status_table_name())
    warehouse = _warehouse_id()
    lim = max(1, min(int(limit), 2000))
    result = execute_sql(
        statement=f"""
            SELECT * FROM {ref.fqn}
            ORDER BY updated_at DESC
            LIMIT {lim}
        """,
        warehouse_id=warehouse,
    )
    return [_row_from_sql(r) for r in result.get("rows") or []]


def pipeline_flags(row: dict[str, Any]) -> dict[str, bool]:
    """Derive stage flags from stored booleans; infer from ``status`` only as fallback."""
    status = str(row.get("status") or "")
    parsed_col = _sql_bool(row.get("parsed"))
    chunked_col = _sql_bool(row.get("chunked"))
    embedded_col = _sql_bool(row.get("embedded"))
    return {
        "parsed": parsed_col
        or status in ("parsed", "chunking", "chunked", "embedding", "ready"),
        "chunked": chunked_col
        or status in ("chunked", "embedding", "ready")
        or int(row.get("chunk_count") or 0) > 0,
        "embedded": embedded_col or status == "ready",
    }


def assert_stage_allowed(row: dict[str, Any], stage: str) -> None:
    from app.api.errors import ConflictError, ValidationError

    status = str(row.get("status") or "")
    if status in _ACTIVE_STATUSES:
        raise ConflictError(f"Document is already processing (status={status})")
    flags = pipeline_flags(row)
    if stage == "parse":
        if status == "ready":
            raise ValidationError("Document is already completed")
        return
    if stage == "chunk":
        if not flags["parsed"]:
            raise ValidationError("Parse this document before chunking")
        if flags["embedded"]:
            raise ValidationError("Document is already completed")
        return
    if not flags["chunked"]:
        raise ValidationError("Chunk this document before embedding")
    if flags["embedded"]:
        raise ValidationError("Document is already embedded")
