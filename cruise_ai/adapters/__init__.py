"""
cruise_ai.adapters -- Pluggable scanner adapters.

Re-exports the public API so callers can write::

    from cruise_ai.adapters import Session, Adapter, run_adapters
"""

from cruise_ai.adapters._base import Adapter, GitLikeAdapter, Session
from cruise_ai.adapters._registry import run_adapters

__all__ = [
    "Adapter",
    "GitLikeAdapter",
    "Session",
    "run_adapters",
]
