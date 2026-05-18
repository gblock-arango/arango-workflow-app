"""Unit tests for app.db.pagination — cursor encode/decode, edge cases."""

from __future__ import annotations

import base64
import json

import pytest

from app.db.pagination import decode_cursor, encode_cursor


class TestEncodeCursor:
    def test_roundtrip_string_value(self):
        cursor = encode_cursor("2026-01-01T00:00:00", "doc123")
        val, key = decode_cursor(cursor)
        assert val == "2026-01-01T00:00:00"
        assert key == "doc123"

    def test_roundtrip_integer_value(self):
        cursor = encode_cursor(42, "key99")
        val, key = decode_cursor(cursor)
        assert val == 42
        assert key == "key99"

    def test_roundtrip_float_value(self):
        cursor = encode_cursor(3.14, "pi_doc")
        val, key = decode_cursor(cursor)
        assert val == 3.14
        assert key == "pi_doc"

    def test_roundtrip_none_value(self):
        cursor = encode_cursor(None, "null_key")
        val, key = decode_cursor(cursor)
        assert val is None
        assert key == "null_key"

    def test_cursor_is_base64_encoded(self):
        cursor = encode_cursor("test", "k1")
        decoded_bytes = base64.urlsafe_b64decode(cursor.encode())
        payload = json.loads(decoded_bytes)
        assert "v" in payload
        assert "k" in payload

    def test_cursor_is_url_safe(self):
        cursor = encode_cursor("special/chars=test+value", "key/with+stuff")
        assert isinstance(cursor, str)
        val, key = decode_cursor(cursor)
        assert val == "special/chars=test+value"
        assert key == "key/with+stuff"


class TestDecodeCursor:
    def test_invalid_base64_raises(self):
        with pytest.raises((ValueError, UnicodeDecodeError, KeyError)):
            decode_cursor("not-valid-base64!!!")

    def test_invalid_json_raises(self):
        bad_cursor = base64.urlsafe_b64encode(b"not json").decode()
        with pytest.raises(json.JSONDecodeError):
            decode_cursor(bad_cursor)

    def test_missing_fields_raises(self):
        bad_cursor = base64.urlsafe_b64encode(json.dumps({"x": 1}).encode()).decode()
        with pytest.raises(KeyError):
            decode_cursor(bad_cursor)
