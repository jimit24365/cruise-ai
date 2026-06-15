"""
nextmillionai.adapters._registry -- Adapter discovery and orchestration.

Discovers installed adapters, runs them with consent gating,
collects Session objects and raw data, then feeds project paths
to the git adapter.
"""

from __future__ import annotations

from nextmillionai.adapters._base import Adapter, Session
from nextmillionai.adapters.claude_code import ClaudeCodeAdapter
from nextmillionai.adapters.claude_desktop import ClaudeDesktopAdapter
from nextmillionai.adapters.codex import CodexAdapter
from nextmillionai.adapters.cursor import CursorAdapter
from nextmillionai.adapters.git import GitAdapter


def get_session_adapters() -> list[Adapter]:
    """Return all session-producing adapters in scan order.

    Reads path constants from ``nextmillionai.scanner`` at call time
    so that monkeypatching in tests propagates correctly.
    """
    import nextmillionai.scanner as scanner_mod
    from nextmillionai.adapters.local_tools import (
        get_local_tool_adapters,
        load_custom_adapters,
    )

    adapters: list[Adapter] = [
        ClaudeCodeAdapter(projects_dir=scanner_mod.CLAUDE_PROJECTS_DIR),
        CursorAdapter(
            cursor_dir=scanner_mod.CURSOR_DIR,
            db_path=scanner_mod.CURSOR_DB_PATH,
            plans_dir=scanner_mod.CURSOR_PLANS_DIR,
            projects_dir=scanner_mod.CURSOR_PROJECTS_DIR,
            app_user_dir=scanner_mod.CURSOR_APP_USER_DIR,
        ),
        CodexAdapter(sessions_dir=scanner_mod.CODEX_SESSIONS_DIR),
        # Experimental, low-fidelity, opt-in — default consent is OFF
        ClaudeDesktopAdapter(),
    ]
    # Wider tool field (Aider/Cline/Continue/Copilot/OpenCode/Windsurf/Zed/
    # JetBrains/Cody/Antigravity) + user-registered custom adapters — one
    # consent group ("other_tools"), per-adapter fidelity declared in raw data.
    adapters.extend(get_local_tool_adapters())
    adapters.extend(load_custom_adapters())
    return adapters


def get_git_adapter() -> GitAdapter:
    """Return the git adapter."""
    return GitAdapter()


def run_adapters(
    project_filter: str | None = None,
    enabled_sources: dict[str, bool] | None = None,
    collection_config: dict | None = None,
) -> tuple[list[Session], dict[str, dict | None], dict | None]:
    """Run all adapters and collect results.

    Parameters
    ----------
    project_filter:
        If set, limit scanning to a single project path.
    enabled_sources:
        Per-source toggle dict. ``None`` enables all.
    collection_config:
        Collection scope from ``collection_config.json``.
        Keys: ``window`` (``"all"`` | int), ``repos`` (``"all"`` | list[str]).

    Returns
    -------
    (sessions, raw_data_by_tool, git_data)

        - sessions: flat list of Session objects from all tools
        - raw_data_by_tool: {"claude_code": {...}, "cursor": {...}, ...}
        - git_data: result from GitAdapter.scan_projects()
    """
    if enabled_sources is None:
        enabled_sources = {
            "claude_code": True,
            "cursor": True,
            "codex": True,
            "git": True,
            "other_tools": True,
            "local_models": True,
            # Experimental + low-fidelity: never enabled silently
            "claude_desktop": False,
        }

    if collection_config is None:
        collection_config = {}

    all_sessions: list[Session] = []
    raw_data: dict[str, dict | None] = {}

    # Map adapter names to consent keys. Everything outside the three
    # first-class tools shares the "other_tools" group — one calibrate
    # question, not eight (same privacy class: local own-tool logs).
    _consent_keys = {
        "claude_code": "claude_code",
        "cursor": "cursor",
        "codex": "codex",
        "claude_desktop": "claude_desktop",
    }

    for adapter in get_session_adapters():
        consent_key = _consent_keys.get(adapter.name, "other_tools")
        if not enabled_sources.get(consent_key, False):
            raw_data[adapter.name] = None
            continue

        if not adapter.detect():
            raw_data[adapter.name] = None
            continue

        sessions = adapter.scan(project_filter)
        all_sessions.extend(sessions)
        raw_data[adapter.name] = adapter.raw_data()

    # Collect project paths from sessions for git scanning
    project_paths: list[str] = []
    seen_paths: set[str] = set()
    for s in all_sessions:
        if s.project_path and s.project_path not in seen_paths:
            seen_paths.add(s.project_path)
            project_paths.append(s.project_path)

    # Extract window and repo_filter from collection_config
    window = collection_config.get("window")
    repos_cfg = collection_config.get("repos", "all")
    repo_filter: list[str] | None = None
    if isinstance(repos_cfg, list):
        repo_filter = repos_cfg

    # Run git adapter
    git_data: dict | None = None
    if enabled_sources.get("git", False):
        git_adapter = get_git_adapter()
        git_data = git_adapter.scan_projects(
            project_paths,
            project_filter=project_filter,
            window=window,
            repo_filter=repo_filter,
        )

    return all_sessions, raw_data, git_data
