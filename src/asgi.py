"""ASGI entrypoint for Databricks Apps (``PYTHONPATH=src``)."""

from app.main import app

__all__ = ["app"]
