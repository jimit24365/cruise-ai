"""
nextmillionai.adapters.git -- Git history adapter.

Scans git log and detects tech stack for discovered project paths.
Auto-discovers repos under common roots and respects collection window.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from nextmillionai.scanner import (
    detect_tech_stack,
    git_run,
)

# Directory names that encode absolute paths (Cursor/Claude storage dirs)
_ENCODED_PATH_RE = re.compile(r"^Users-[A-Za-z0-9]+-")


def _log(msg: str) -> None:
    if os.environ.get("NEXTMILLIONAI_VERBOSE"):
        print(f"[scanner] {msg}", file=sys.stderr)


# Roots to search for git repos during auto-discovery.
_COMMON_ROOTS = [
    Path.home(),
    Path.home() / "code",
    Path.home() / "projects",
    Path.home() / "Documents",
    Path.home() / "Downloads",
]


class GitAdapter:
    """Adapter that scans git history for discovered projects."""

    def __init__(self) -> None:
        self._raw: dict | None = None

    @property
    def name(self) -> str:
        return "git"

    def detect(self) -> bool:
        return True  # git is discovered from project paths

    # ── Auto-discovery ────────────────────────────────────────────────────

    def _discover_repos(self, max_depth: int = 3) -> list[Path]:
        """Find git repos under common roots, depth-limited."""
        found: set[Path] = set()
        roots = list(_COMMON_ROOTS)
        try:
            cwd = Path.cwd()
            roots.append(cwd)
        except OSError:
            pass
        for root in roots:
            if not root.exists():
                continue
            self._walk_for_git(root, found, depth=0, max_depth=max_depth)
        return sorted(found)

    def _walk_for_git(
        self,
        path: Path,
        found: set[Path],
        depth: int,
        max_depth: int,
    ) -> None:
        if depth > max_depth:
            return
        try:
            for child in path.iterdir():
                if not child.is_dir() or child.name.startswith("."):
                    continue
                # Skip storage-encoded path names ("Users-apple-Documents-x")
                # — tool artifacts, not real projects
                if _ENCODED_PATH_RE.match(child.name):
                    continue
                if (child / ".git").is_dir():
                    found.add(child.resolve())
                elif depth < max_depth:
                    self._walk_for_git(child, found, depth + 1, max_depth)
        except PermissionError:
            pass

    # ── Main scan ─────────────────────────────────────────────────────────

    def scan_projects(
        self,
        project_paths: list[str],
        project_filter: str | None = None,
        window: str | int | None = None,
        repo_filter: list[str] | None = None,
    ) -> dict | None:
        """Scan git history for projects.

        Parameters
        ----------
        project_paths:
            Paths derived from session adapters.
        project_filter:
            If set, scan only this single path.
        window:
            ``"all"`` for full history, an int for N days, or ``None``
            for the legacy 6-month default.
        repo_filter:
            If a list, only scan repos whose resolved path is in the list.
        """
        paths: list[Path] = []

        if project_filter:
            p = Path(os.path.expanduser(project_filter)).resolve()
            if p.exists():
                paths = [p]
        else:
            # Merge session-derived paths with auto-discovered repos
            session_paths = {Path(p).resolve() for p in project_paths}
            discovered = set(self._discover_repos())
            merged = session_paths | discovered
            paths = sorted(merged)

        # Apply repo_filter if specified
        if repo_filter is not None:
            resolved_filter = {Path(r).resolve() for r in repo_filter}
            paths = [p for p in paths if p.resolve() in resolved_filter]

        if not paths:
            _log("Git: no project paths discovered")
            self._raw = None
            return None

        _log(f"Git: scanning {len(paths)} projects...")

        # Build --since arg from window
        since_args: list[str] = []
        if window is None:
            since_args = ["--since=6 months ago"]
        elif isinstance(window, int):
            since_args = [f"--since={window} days ago"]
        # window == "all": no --since flag

        projects = []
        auto_discovered_count = 0
        session_derived_count = 0
        session_set = {Path(p).resolve() for p in project_paths}

        for proj_path in paths:
            # Session-derived paths can be stale or never-were-paths;
            # only actual git repos belong in the project list
            if not (proj_path / ".git").is_dir():
                continue
            name = proj_path.name

            # Track source for reporting
            if proj_path.resolve() in session_set:
                session_derived_count += 1
            else:
                auto_discovered_count += 1

            output = git_run(
                ["log", "--oneline"] + since_args,
                cwd=proj_path,
            )
            feat_count = 0
            fix_count = 0
            if output:
                for cline in output.splitlines():
                    parts = cline.strip().split(" ", 1)
                    if len(parts) > 1:
                        cmsg = parts[1].lower()
                        if cmsg.startswith(("feat:", "feat(", "feature:", "add:")):
                            feat_count += 1
                        elif cmsg.startswith(("fix:", "fix(", "bugfix:", "hotfix:")):
                            fix_count += 1
            commit_count = len(output.splitlines()) if output else 0

            # Get commit author dates for activityByDay
            date_output = git_run(
                ["log", "--format=%aI"] + since_args,
                cwd=proj_path,
            )
            commit_dates = date_output.splitlines() if date_output else []

            stack = detect_tech_stack(proj_path)
            # ordered de-dupe: TypeScript can be both a language and a
            # framework-map label
            stack_labels = list(dict.fromkeys(stack["languages"] + stack["frameworks"]))

            projects.append(
                {
                    "path": str(proj_path),
                    "name": name,
                    "commits_6m": commit_count,
                    "stack": stack_labels,
                    "languages": stack["languages"],
                    "frameworks": stack["frameworks"],
                    "tools": stack["tools"],
                    "aiFrameworks": stack.get("aiFrameworks", []),
                    "databases": stack.get("databases", []),
                    "cloud": stack.get("cloud", []),
                    "harness": stack.get("harness", {}),
                    "feat_commits": feat_count,
                    "fix_commits": fix_count,
                    "commit_dates": commit_dates,
                }
            )

            window_label = (
                "all" if window == "all" else (f"{window}d" if isinstance(window, int) else "6m")
            )
            _log(f"  {name}: {commit_count} commits ({window_label}), stack={stack_labels}")

        if not projects:
            self._raw = None
            return None

        self._raw = {
            "projects": projects,
            "auto_discovered_repos": auto_discovered_count,
            "session_derived_repos": session_derived_count,
            "total_repos": len(projects),
            "window": window if window is not None else "6m_default",
        }
        return self._raw

    def raw_data(self) -> dict | None:
        return self._raw
