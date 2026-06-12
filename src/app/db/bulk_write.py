"""Batched document and edge writes for Arango (direct or gateway)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import quote

from app.config import settings
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.types import StandardDatabase
from app.db.utils import run_aql

log = logging.getLogger(__name__)

ProgressFn = Callable[[int, int, int], None]


def _q(value: str) -> str:
    return quote(str(value), safe="")


def write_batch_size(batch_size: int | None) -> int:
    if batch_size is not None:
        return max(1, batch_size)
    return max(1, int(settings.arango_write_batch_size))


def http_batch_writes_enabled() -> bool:
    raw = (os.environ.get("ARANGO_HTTP_BATCH_WRITES") or "true").strip().lower()
    return raw not in ("0", "false", "no")


def _gateway_client(db: StandardDatabase) -> Any | None:
    from app.db.gateway_database import GatewayDatabase

    if not isinstance(db, GatewayDatabase):
        return None
    client = db._client
    if client is None or not hasattr(client, "request_batch"):
        return None
    return client


def bulk_insert_documents(
    db: StandardDatabase,
    collection: str,
    documents: list[dict[str, Any]],
    *,
    batch_size: int | None = None,
    overwrite_mode: str = "replace",
    is_edge: bool = False,
    on_batch_progress: ProgressFn | None = None,
) -> int:
    """Insert documents via batched AQL ``INSERT`` (one round-trip per batch).

    Returns the number of documents submitted for insert.
    """
    if not documents:
        return 0

    size = write_batch_size(batch_size)
    written = 0

    edge_merge = (
        """
        FOR doc IN @docs
          INSERT MERGE({ _from: doc._from, _to: doc._to }, doc) INTO @@col
          OPTIONS { overwriteMode: @mode }
        """
        if is_edge
        else """
        FOR doc IN @docs
          INSERT doc INTO @@col
          OPTIONS { overwriteMode: @mode }
        """
    )

    for offset in range(0, len(documents), size):
        batch = documents[offset : offset + size]
        run_aql(
            db,
            edge_merge,
            bind_vars={"docs": batch, "@col": collection, "mode": overwrite_mode},
        )
        written += len(batch)
        if on_batch_progress:
            on_batch_progress(written, len(documents), size)

    return written


def bulk_insert_temporal_edges_if_absent(
    db: StandardDatabase,
    collection: str,
    edges: list[dict[str, Any]],
    *,
    batch_size: int | None = None,
) -> int:
    """Insert live temporal edges only when the endpoint triple is absent.

    Batches the idempotency probe + insert into one AQL statement per batch,
    matching the contract of :func:`app.db.utils.insert_temporal_edge_if_absent`.
    """
    if not edges:
        return 0

    size = write_batch_size(batch_size)
    inserted = 0

    query = """
    FOR edge IN @edges
      LET exists = (
        FOR e IN @@col
          FILTER e._from == edge._from
            AND e._to == edge._to
            AND e.ontology_id == edge.ontology_id
            AND e.expired == @never
          LIMIT 1
          RETURN 1
      )
      FILTER LENGTH(exists) == 0
      INSERT MERGE({ _from: edge._from, _to: edge._to }, edge) INTO @@col
    """

    for offset in range(0, len(edges), size):
        batch = edges[offset : offset + size]
        run_aql(
            db,
            query,
            bind_vars={"edges": batch, "@col": collection, "never": NEVER_EXPIRES},
        )
        inserted += len(batch)

    return inserted


def _parse_gateway_insert_many_body(body: Any, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(body, list):
        items = body
    elif isinstance(body, dict):
        raw = body.get("result") or body.get("documents")
        items = raw if isinstance(raw, list) else [body]
    else:
        items = []

    inserted: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        if item.get("error") is True:
            log.warning(
                "gateway batch insert item failed: %s",
                item.get("errorMessage", item),
            )
            continue
        merged = dict(batch[i]) if i < len(batch) else {}
        for key in ("_key", "_id", "_rev"):
            if key in item:
                merged[key] = item[key]
        if "new" in item and isinstance(item["new"], dict):
            merged.update(item["new"])
        if merged.get("_key") or merged.get("_id"):
            inserted.append(merged)
    return inserted


def insert_many_via_http_batch(
    db: StandardDatabase,
    collection: str,
    documents: Sequence[dict[str, Any]],
    *,
    batch_size: int | None = None,
    on_batch_progress: ProgressFn | None = None,
) -> list[dict[str, Any]] | None:
    """Pack multiple Arango ``insert_many`` REST calls into one gateway batch hop.

    Returns ``None`` when the gateway batch path is unavailable so callers can
    fall back to sequential ``insert_many``.
    """
    if not documents:
        return []

    client = _gateway_client(db)
    if client is None or not http_batch_writes_enabled():
        return None

    size = write_batch_size(batch_size)
    batches = [list(documents[i : i + size]) for i in range(0, len(documents), size)]
    if len(batches) <= 1:
        return None

    db_name = getattr(db, "name", settings.arango_db)
    requests = [
        {
            "method": "POST",
            "path": f"/_db/{_q(db_name)}/_api/document/{_q(collection)}",
            "body": batch,
        }
        for batch in batches
    ]

    try:
        batch_result = client.request_batch(
            requests,
            parallel=True,
            max_workers=min(8, len(requests)),
        )
    except Exception as exc:
        log.warning("gateway document insert batch failed (%s); falling back", exc)
        return None

    if batch_result.get("error") and not batch_result.get("results"):
        log.warning("gateway document insert batch failed: %s", batch_result.get("error"))
        return None

    inserted: list[dict[str, Any]] = []
    results = batch_result.get("results") or []
    for i, row in enumerate(results):
        if not isinstance(row, dict) or not row.get("ok"):
            log.warning(
                "gateway batch insert request %d failed: %s",
                i,
                row.get("error") if isinstance(row, dict) else row,
            )
            continue
        batch = batches[i] if i < len(batches) else []
        inserted.extend(_parse_gateway_insert_many_body(row.get("body"), batch))
        if on_batch_progress and batch:
            on_batch_progress(len(inserted), len(documents), size)

    return inserted
