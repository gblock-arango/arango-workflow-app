"""Fresh-database batch schema bootstrap."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from migrations.bootstrap_batch import (
    bootstrap_fresh_schema,
    can_bootstrap_fresh,
    core_collections_present,
    should_use_batch_bootstrap,
)
from migrations.runner import apply_all, discover_migrations


class TestCanBootstrapFresh:
    def test_true_when_no_migrations_applied(self) -> None:
        assert can_bootstrap_fresh(set()) is True

    def test_false_when_some_applied(self) -> None:
        assert can_bootstrap_fresh({"001_initial_collections"}) is False


class TestBootstrapFreshSchema:
    def test_lists_catalog_once(self) -> None:
        db = MagicMock()
        db.collections.return_value = [{"name": "documents"}, {"name": "chunks"}]
        db.graphs.return_value = []
        db.views.return_value = []
        col = MagicMock()
        col.indexes.return_value = []
        db.collection.return_value = col

        bootstrap_fresh_schema(db)

        db.collections.assert_called_once()
        db.graphs.assert_called_once()
        db.views.assert_called_once()
        assert db.create_collection.call_count > 0
        assert db.create_graph.call_count == 2


class TestApplyAllBatchPath:
    def test_fresh_database_uses_batch_bootstrap(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = False
        col = MagicMock()
        col.has.return_value = False
        db.collection.return_value = col

        all_names = discover_migrations()
        messages: list[str] = []

        with (
            patch("migrations.runner._load_schema_state", return_value={}),
            patch(
                "migrations.bootstrap_batch.bootstrap_fresh_schema",
            ) as mock_bootstrap,
        ):
            applied = apply_all(
                db,
                on_progress=lambda msg, _p: messages.append(msg),
            )

        mock_bootstrap.assert_called_once()
        assert applied == all_names
        assert any("Batch schema bootstrap" in m or "one batch" in m for m in messages)

    def test_collections_present_uses_batch_even_with_partial_state(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        col.has.return_value = False
        db.collection.return_value = col

        all_names = discover_migrations()
        state = {"applied_migrations": [{"name": "001_initial_collections", "applied_at": 1.0}]}

        with (
            patch("migrations.runner.discover_migrations", return_value=all_names),
            patch("migrations.runner._load_schema_state", return_value=state),
            patch(
                "migrations.bootstrap_batch.core_collections_present",
                return_value=True,
            ),
            patch("migrations.bootstrap_batch.bootstrap_fresh_schema") as mock_bootstrap,
        ):
            applied = apply_all(db)

        mock_bootstrap.assert_called_once()
        expected = [n for n in all_names if n != "001_initial_collections"]
        assert applied == expected

    def test_core_collections_present_checks_catalog(self) -> None:
        db = MagicMock()
        db.collections.return_value = [{"name": n} for n in ("documents", "chunks")]
        assert core_collections_present(db) is False

    def test_should_use_batch_when_collections_exist(self) -> None:
        db = MagicMock()
        with patch(
            "migrations.bootstrap_batch.core_collections_present",
            return_value=True,
        ):
            assert should_use_batch_bootstrap(db, {"001_initial_collections"}, ["010_process_graph"])
