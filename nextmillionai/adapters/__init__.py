"""
nextmillionai.adapters -- Pluggable scanner adapters.

Re-exports the public API so callers can write::

    from nextmillionai.adapters import Session, Adapter, run_adapters
"""

from nextmillionai.adapters._base import Adapter, GitLikeAdapter, Session
from nextmillionai.adapters._registry import run_adapters

__all__ = [
    "Adapter",
    "GitLikeAdapter",
    "Session",
    "run_adapters",
]
