"""cruise_ai.recommendations._session_compat — helper for dual-mode session access.

Provides utilities to access session fields regardless of whether
the session is a dict (legacy) or a Session dataclass (adapters).
"""

from __future__ import annotations

from typing import Any


def session_field(session: Any, field_name: str, default: Any = None) -> Any:
    """Get a field from a session regardless of whether it's a dict or dataclass.

    Args:
        session: A Session dataclass instance or a plain dict.
        field_name: The field/key to retrieve.
        default: Fallback value if field is missing.

    Returns:
        The field value, or default if not found.
    """
    if isinstance(session, dict):
        return session.get(field_name, default)
    return getattr(session, field_name, default)
