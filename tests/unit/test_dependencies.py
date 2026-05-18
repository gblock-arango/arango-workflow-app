"""Tests for API dependencies (get_or_404, RBAC helpers)."""

from __future__ import annotations

import pytest

from app.api.dependencies import get_or_404
from app.api.errors import NotFoundError


class TestGetOr404:
    def test_returns_result_when_not_none(self):
        result = get_or_404({"_key": "abc"}, "Document", "abc")
        assert result["_key"] == "abc"

    def test_raises_not_found_when_none(self):
        with pytest.raises(NotFoundError) as exc_info:
            get_or_404(None, "Document", "abc123")
        assert "abc123" in str(exc_info.value)

    def test_error_details_include_entity_id(self):
        with pytest.raises(NotFoundError) as exc_info:
            get_or_404(None, "Organization", "org_99")
        assert exc_info.value.details["organization_id"] == "org_99"
