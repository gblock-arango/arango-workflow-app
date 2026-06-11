"""Migration runner progress callbacks for Diagnostics."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from migrations.runner import apply_all, discover_migrations


class TestMigrationRunnerProgress:
    def test_reports_each_pending_migration(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        col.has.return_value = False
        db.collection.return_value = col

        messages: list[str] = []

        def on_progress(message: str, progress: dict | None) -> None:
            messages.append(message)
            assert progress is not None
            assert progress.get("phase") == "schema_migration"

        pending = discover_migrations()[:2]
        with patch("migrations.runner.discover_migrations", return_value=pending):
            with patch("migrations.runner._load_schema_state", return_value={}):
                with patch(
                    "migrations.bootstrap_batch.bootstrap_fresh_schema",
                    side_effect=RuntimeError("force sequential fallback"),
                ):
                    with patch("migrations.runner.importlib.import_module") as mock_import:
                        mod = MagicMock()
                        mod.up = MagicMock()
                        mock_import.return_value = mod
                        applied = apply_all(db, on_progress=on_progress, heartbeat_sec=60.0)

        assert applied == pending
        assert any("Migration 1/2" in m for m in messages)
        assert any("done:" in m for m in messages)

    def test_skipped_migrations_report_up_to_date(self) -> None:
        db = MagicMock()
        all_names = discover_migrations()
        state = {
            "applied_migrations": [{"name": n, "applied_at": 1.0} for n in all_names],
        }
        messages: list[str] = []

        with patch("migrations.runner.discover_migrations", return_value=all_names):
            with patch("migrations.runner._load_schema_state", return_value=state):
                applied = apply_all(
                    db,
                    on_progress=lambda msg, _p: messages.append(msg),
                )

        assert applied == []
        assert any("up to date" in m for m in messages)
