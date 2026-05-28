"""Unit tests for serving endpoint name normalization."""

from __future__ import annotations

from app.llm.databricks_serving import normalize_serving_endpoint_name


def test_bge_large_foundation_model_alias():
    assert (
        normalize_serving_endpoint_name("bge_large_en_v1_5")
        == "databricks-bge-large-en"
    )


def test_gte_large_foundation_model_alias():
    assert (
        normalize_serving_endpoint_name("gte_large_en_v1_5")
        == "databricks-gte-large-en"
    )


def test_passthrough_databricks_endpoint():
    assert (
        normalize_serving_endpoint_name("databricks-bge-large-en")
        == "databricks-bge-large-en"
    )


def test_passthrough_custom_endpoint_name():
    assert normalize_serving_endpoint_name("my-custom-embedding-endpoint") == (
        "my-custom-embedding-endpoint"
    )
