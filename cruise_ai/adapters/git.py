"""
cruise_ai.adapters.git -- Git history adapter.

Scans git log and detects tech stack for discovered project paths.
Auto-discovers repos under common roots and respects collection window.
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

from cruise_ai.scanner import (
    detect_tech_stack,
    git_run,
)

# Directory names that encode absolute paths (Cursor/Claude storage dirs)
_ENCODED_PATH_RE = re.compile(r"^Users-[A-Za-z0-9]+-")


def _log(msg: str) -> None:
    if os.environ.get("CRUISE_AI_VERBOSE"):
        print(f"[scanner] {msg}", file=sys.stderr)


def _progress(msg: str) -> None:
    """One-line progress to stderr so a long git scan never looks frozen.

    Auto-discovery on a machine with no AI-tool sessions (git is the only
    source) can find many repos; without feedback users assume a hang and
    Ctrl+C. Suppressed when stderr isn't a TTY (logs/CI stay clean).
    """
    try:
        if sys.stderr.isatty():
            print(f"\r  {msg}\033[K", end="", file=sys.stderr, flush=True)
    except Exception:
        pass


# Roots to search for git repos during auto-discovery.
_COMMON_ROOTS = [
    Path.home(),
    Path.home() / "code",
    Path.home() / "projects",
    Path.home() / "Documents",
    Path.home() / "Downloads",
]

# Big, slow, or vendored directories that never hold the user's own
# project repos — skipped during auto-discovery so walking $HOME doesn't
# descend into ~/Library, conda installs, node_modules, etc. (the real
# cause of multi-minute "hangs" on IDE-less machines).
_SKIP_WALK_DIRS = frozenset(
    {
        "Library",
        "Applications",
        "Movies",
        "Music",
        "Pictures",
        "node_modules",
        "vendor",
        "Pods",
        "DerivedData",
        "anaconda3",
        "miniconda3",
        "miniforge3",
        "venv",
        ".venv",
        "env",
        "site-packages",
        "dist-packages",
        "__pycache__",
        ".Trash",
        ".cache",
    }
)

# Bounds so auto-discovery can never run away on a huge home tree.
_MAX_DISCOVERED_REPOS = 300
_DISCOVERY_BUDGET_SEC = 20.0
# Overall wall-clock budget for scanning git history across all repos.
# Past this, remaining repos are skipped and we return what we have —
# better a partial, honest scan than a process that appears hung.
_SCAN_BUDGET_SEC = 90.0


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
        """Find git repos under common roots, depth-limited.

        Bounded by a wall-clock budget and a repo cap: a machine with no
        AI-tool sessions (git is the only source) must never spend minutes
        walking the entire home directory tree.
        """
        found: set[Path] = set()
        deadline = time.monotonic() + _DISCOVERY_BUDGET_SEC
        roots = list(_COMMON_ROOTS)
        try:
            cwd = Path.cwd()
            roots.append(cwd)
        except OSError:
            pass
        for root in roots:
            if time.monotonic() > deadline or len(found) >= _MAX_DISCOVERED_REPOS:
                break
            if not root.exists():
                continue
            self._walk_for_git(root, found, depth=0, max_depth=max_depth, deadline=deadline)
        return sorted(found)

    def _walk_for_git(
        self,
        path: Path,
        found: set[Path],
        depth: int,
        max_depth: int,
        deadline: float | None = None,
    ) -> None:
        if depth > max_depth:
            return
        if len(found) >= _MAX_DISCOVERED_REPOS:
            return
        if deadline is not None and time.monotonic() > deadline:
            return
        try:
            for child in path.iterdir():
                if not child.is_dir() or child.name.startswith("."):
                    continue
                # Skip storage-encoded path names ("Users-apple-Documents-x")
                # — tool artifacts, not real projects
                if _ENCODED_PATH_RE.match(child.name):
                    continue
                # Skip huge/vendored trees that never hold the user's repos
                if child.name in _SKIP_WALK_DIRS:
                    continue
                if (child / ".git").is_dir():
                    found.add(child.resolve())
                    if len(found) >= _MAX_DISCOVERED_REPOS:
                        return
                elif depth < max_depth:
                    if deadline is not None and time.monotonic() > deadline:
                        return
                    self._walk_for_git(child, found, depth + 1, max_depth, deadline)
        except (PermissionError, OSError):
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

        # Only actual git repos belong in the project list; resolve the
        # real count up front so progress + the time budget are honest.
        repo_paths = [p for p in paths if (p / ".git").is_dir()]
        total_repos = len(repo_paths)
        deadline = time.monotonic() + _SCAN_BUDGET_SEC
        truncated = False

        for idx, proj_path in enumerate(repo_paths, start=1):
            # Stop cleanly if the overall budget is blown — a partial,
            # honest scan beats a process that looks frozen.
            if time.monotonic() > deadline:
                truncated = True
                _log(
                    f"Git: scan budget reached after {idx - 1}/{total_repos} repos; "
                    "skipping the rest"
                )
                break
            if total_repos > 1:
                _progress(f"Scanning git history… repo {idx}/{total_repos} ({proj_path.name})")
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

        # Clear the in-place progress line so it doesn't linger before the
        # next step's output.
        if total_repos > 1:
            try:
                if sys.stderr.isatty():
                    print("\r\033[K", end="", file=sys.stderr, flush=True)
            except Exception:
                pass

        if not projects:
            self._raw = None
            return None

        self._raw = {
            "projects": projects,
            "auto_discovered_repos": auto_discovered_count,
            "session_derived_repos": session_derived_count,
            "total_repos": len(projects),
            "scan_truncated": truncated,
            "window": window if window is not None else "6m_default",
        }
        return self._raw

    def raw_data(self) -> dict | None:
        return self._raw
