"""Unit tests for UC catalog annotation helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import uc_catalog


def test_sql_string_literal_escapes_quotes():
    assert uc_catalog._sql_string_literal("it's fine") == "'it''s fine'"


def test_parse_full_name_rejects_invalid():
    with pytest.raises(ValueError):
        uc_catalog._parse_full_name("only.two")


@patch("app.services.uc_catalog.execute_sql")
@patch("app.services.uc_catalog.AppConfig")
def test_save_uc_table_annotations_builds_sql(mock_cfg: MagicMock, mock_sql: MagicMock):
    mock_cfg.return_value.DATABRICKS_SQL_WAREHOUSE_ID = "wh-1"
    result = uc_catalog.save_uc_table_annotations(
        "workspace.default.my_table",
        table_comment="Table desc",
        columns=[{"name": "id", "comment": "Primary key"}],
    )
    assert result["status"] == "ok"
    assert mock_sql.call_count == 2
    table_stmt = mock_sql.call_args_list[0][0][0]
    col_stmt = mock_sql.call_args_list[1][0][0]
    assert "COMMENT ON TABLE workspace.default.my_table" in table_stmt
    assert "ALTER TABLE workspace.default.my_table ALTER COLUMN `id`" in col_stmt
