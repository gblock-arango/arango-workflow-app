"""Per-run database resolution for extraction APIs."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.api.errors import NotFoundError


def test_get_run_falls_back_when_provided_db_misses():
    from app.services import extraction as extraction_svc

    wrong_db = MagicMock()
    wrong_db.has_collection.return_value = True

    found_run = {
        "_key": "run_e0cf37d48a03",
        "status": "preparing",
        "arango_database": "AutoGraph_1",
        "stats": {},
    }
    auto_db = MagicMock()
    auto_db.has_collection.return_value = True

    def fake_doc_get(col, key):
        if key != "run_e0cf37d48a03":
            return None
        if col is wrong_db.collection.return_value:
            return None
        return found_run

    with (
        patch.object(extraction_svc, "doc_get", side_effect=fake_doc_get),
        patch(
            "app.db.arango_database_names.discover_extraction_databases",
            return_value=["OntoExtract", "AutoGraph_1"],
        ),
        patch.object(extraction_svc, "get_db", return_value=auto_db),
        patch.object(extraction_svc, "clear_active_arango_database"),
        patch.object(extraction_svc, "set_active_arango_database"),
        patch.object(extraction_svc, "_apply_run_arango_database"),
    ):
        result = extraction_svc.get_run(wrong_db, run_id="run_e0cf37d48a03")

    assert result["_key"] == "run_e0cf37d48a03"
    assert result["arango_database"] == "AutoGraph_1"


def test_db_for_run_pins_database_from_discovered_run():
    from app.services import extraction as extraction_svc

    mock_db = MagicMock()
    with (
        patch.object(
            extraction_svc,
            "get_run",
            return_value={"_key": "run_abc", "arango_database": "AutoGraph_1", "stats": {}},
        ),
        patch.object(extraction_svc, "set_active_arango_database") as mock_pin,
        patch.object(extraction_svc, "get_db", return_value=mock_db),
    ):
        db = extraction_svc.db_for_run("run_abc")

    assert db is mock_db
    mock_pin.assert_called_once_with("AutoGraph_1")


def test_get_run_cost_resolves_run_when_wrong_db_passed():
    from app.services import extraction as extraction_svc

    mock_db = MagicMock()
    mock_db.has_collection.return_value = False

    run_doc = {
        "_key": "run_e0cf37d48a03",
        "status": "preparing",
        "arango_database": "AutoGraph_1",
        "model": "gpt-4o-mini",
        "started_at": 1000.0,
        "completed_at": None,
        "stats": {"token_usage": {}},
    }

    with (
        patch.object(extraction_svc, "get_run", return_value=run_doc) as mock_get_run,
        patch.object(extraction_svc, "run_aql", return_value=[]),
    ):
        result = extraction_svc.get_run_cost(mock_db, run_id="run_e0cf37d48a03")

    mock_get_run.assert_called_once_with(mock_db, run_id="run_e0cf37d48a03")
    assert result["run_id"] == "run_e0cf37d48a03"


def test_db_for_run_raises_when_run_missing_everywhere():
    from app.services import extraction as extraction_svc

    with patch.object(
        extraction_svc,
        "get_run",
        side_effect=NotFoundError("Extraction run 'run_missing' not found"),
    ):
        with pytest.raises(NotFoundError):
            extraction_svc.db_for_run("run_missing")
