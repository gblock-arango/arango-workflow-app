"""Compatibility helpers for Python 3.10 (project targets 3.11+)."""

from __future__ import annotations

import sys
from datetime import timezone

if sys.version_info >= (3, 11):
    from datetime import UTC
    from enum import StrEnum
else:
    from enum import Enum

    UTC = timezone.utc

    class StrEnum(str, Enum):
        """Minimal ``enum.StrEnum`` backport for Python 3.10."""

        @staticmethod
        def _generate_next_value_(name: str, start: int, count: int, last_values: list) -> str:
            return name
