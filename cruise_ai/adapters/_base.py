"""
cruise_ai.adapters._base -- Session dataclass and adapter protocols.

Session is the universal container for one AI coding session, regardless
of which tool produced it.  Adapter / GitLikeAdapter are structural
protocols that every scanner must satisfy.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

# `slots` is a pure optimization and only exists on dataclass() in 3.10+.
# Keep it conditional so the package still imports under a 3.9 Python
# (the supported floor is 3.9; slots is simply skipped there).
_DC_KWARGS: dict = {"frozen": True}
if sys.version_info >= (3, 10):
    _DC_KWARGS["slots"] = True


@dataclass(**_DC_KWARGS)
class Session:
    """One AI coding session, tool-agnostic."""

    tool: str  # "claude_code", "cursor", "codex", etc.
    session_id: str
    project_path: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    user_msgs: int = 0
    assistant_msgs: int = 0
    tool_calls_by_type: dict[str, int] = field(default_factory=dict)
    models: list[str] = field(default_factory=list)
    prompt_word_counts: list[int] = field(default_factory=list)
    extras: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class Adapter(Protocol):
    """Protocol for session-producing adapters (Claude Code, Cursor, Codex, ...)."""

    @property
    def name(self) -> str: ...

    def detect(self) -> bool: ...

    def scan(self, project_filter: str | None = None) -> list[Session]: ...

    def raw_data(self) -> dict | None: ...


@runtime_checkable
class GitLikeAdapter(Protocol):
    """Protocol for project-scanning adapters (Git)."""

    @property
    def name(self) -> str: ...

    def detect(self) -> bool: ...

    def scan_projects(
        self,
        project_paths: list[str],
        project_filter: str | None = None,
    ) -> dict | None: ...
