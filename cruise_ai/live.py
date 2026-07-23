"""
cruise_ai.live — Local live-watch for `report --live`.

Polls the local source directories (Claude Code / Cursor / Codex session
stores + the `.git` dirs of already-discovered repos), debounces bursts
of changes, re-runs the normal local assess pipeline, and bumps a
generation counter that the hub streams to open views over
localhost-only SSE.

Privacy: this module never opens a socket and never imports networking.
It reads local file mtimes and invokes the same local CLI assess the
user runs by hand. It is NOT a network path — serving stays in hub.py
(localhost inbound only) and outbound stays in network.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_POLL_INTERVAL = 5.0
DEFAULT_DEBOUNCE = 4.0

# Heavy/no-signal subtrees skipped while fingerprinting. `.git` content is
# watched only via its refs/logs (commits), so `objects` packs are noise.
_SKIP_DIRS = frozenset(["objects", "node_modules", "__pycache__", ".venv", "venv", ".tox", "lfs"])


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def discover_watch_paths() -> list:
    """Return [(source_id, Path)] of existing local dirs worth watching.

    Sessions: the three adapter stores. Repos: the `.git` dir of every
    repo the last scan discovered — commits are the assessment signal;
    mid-edit working-tree churn is not, so the working tree itself is
    deliberately NOT watched.
    """
    home = Path(os.path.expanduser("~"))
    candidates = [
        ("claude_code", home / ".claude" / "projects"),
        ("cursor_ide", home / ".cursor"),
        ("codex_cli", home / ".codex" / "sessions"),
        ("kiro", home / ".kiro" / "sessions" / "cli"),
    ]
    paths = [(sid, p) for sid, p in candidates if p.is_dir()]

    from cruise_ai.paths import scan_results_path

    sr = scan_results_path()
    if sr.is_file():
        try:
            with open(sr) as f:
                data = json.load(f)
            for proj in (data.get("git") or {}).get("projects") or []:
                repo = proj.get("path")
                if not repo:
                    continue
                git_dir = Path(repo) / ".git"
                if git_dir.is_dir():
                    name = proj.get("name") or Path(repo).name
                    paths.append((f"git:{name}", git_dir))
        except (json.JSONDecodeError, OSError):
            pass
    return paths


def tree_fingerprint(root: Path, max_files: int = 50000) -> tuple:
    """Cheap change fingerprint: (file count, newest mtime, total size)."""
    count = 0
    newest = 0.0
    size = 0
    stack = [str(root)]
    while stack and count < max_files:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for entry in it:
                    if entry.name in _SKIP_DIRS:
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                            count += 1
                            size += st.st_size
                            if st.st_mtime > newest:
                                newest = st.st_mtime
                    except OSError:
                        continue
        except OSError:
            continue
    return (count, int(newest), size)


class LiveState:
    """Shared watcher state; the hub reads snapshots and SSE waiters
    block on ``cond`` until the generation bumps."""

    def __init__(self) -> None:
        self.cond = threading.Condition()
        self.live = False
        self.updating = False
        self.generation = 0
        self.last_updated: str | None = None
        self.last_changed: list = []
        self.last_error: str | None = None
        self.sources: list = []

    def _snapshot_locked(self) -> dict:
        return {
            "live": self.live,
            "updating": self.updating,
            "generation": self.generation,
            "lastUpdated": self.last_updated,
            "lastChanged": list(self.last_changed),
            "lastError": self.last_error,
            "sources": [{"id": sid, "path": str(p)} for sid, p in self.sources],
        }

    def snapshot(self) -> dict:
        with self.cond:
            return self._snapshot_locked()

    def set_watching(self, sources: list) -> None:
        with self.cond:
            self.live = True
            self.sources = list(sources)
            self.cond.notify_all()

    def set_updating(self, updating: bool) -> None:
        with self.cond:
            self.updating = updating
            self.cond.notify_all()

    def notify_updated(self, changed: list, error: str | None = None) -> None:
        with self.cond:
            self.updating = False
            self.last_changed = list(changed)
            self.last_error = error
            if error is None:
                self.generation += 1
                self.last_updated = _iso_now()
            self.cond.notify_all()


#: The one shared state the hub serves. A plain module global: the hub
#: and the watcher run in the same process by construction.
STATE = LiveState()


def _run_assess() -> tuple:
    """Recompute the assessment via the normal local CLI (quiet).

    Full recompute by design: scan_results aggregates cross-source
    derived structures (activity union, footprint, harness), so a
    partial per-source merge could silently double-count or go stale.
    A forced full rescan is seconds-fast and always honest.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "cruise_ai", "assess", "--rescan", "--yes"],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip()[-400:]
            return False, tail or f"assess exited {proc.returncode}"
        return True, None
    except Exception as e:  # subprocess timeout / spawn failure
        return False, str(e)


class LiveWatcher(threading.Thread):
    """Poll watch paths, debounce change bursts, recompute, notify."""

    daemon = True

    def __init__(
        self,
        state: LiveState | None = None,
        recompute=None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        debounce: float = DEFAULT_DEBOUNCE,
        paths: list | None = None,
        initial_recompute: bool = True,
    ) -> None:
        super().__init__(name="cruise-ai-live-watcher")
        self.state = state if state is not None else STATE
        self.recompute = recompute if recompute is not None else _run_assess
        self.poll_interval = poll_interval
        self.debounce = debounce
        self.paths = paths
        self.initial_recompute = initial_recompute
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def _do_recompute(self, changed: list) -> None:
        self.state.set_updating(True)
        ok, err = self.recompute()
        self.state.notify_updated(changed, error=None if ok else (err or "recompute failed"))

    def run(self) -> None:
        paths = self.paths if self.paths is not None else discover_watch_paths()
        self.state.set_watching(paths)

        fingerprints = {sid: tree_fingerprint(p) for sid, p in paths}

        # A watcher started against a stale/missing assessment refreshes
        # once up front so "live" is true from the first second.
        if self.initial_recompute:
            self._do_recompute(["startup"])

        pending: set = set()
        last_change = 0.0
        while not self._stop_event.is_set():
            # Tighter ticks while a debounce window is open.
            wait = min(1.0, self.debounce) if pending else self.poll_interval
            if self._stop_event.wait(wait):
                break
            for sid, p in paths:
                fp = tree_fingerprint(p)
                if fp != fingerprints[sid]:
                    fingerprints[sid] = fp
                    pending.add(sid)
                    last_change = time.monotonic()
            if pending and (time.monotonic() - last_change) >= self.debounce:
                changed = sorted(pending)
                pending.clear()
                self._do_recompute(changed)


def start_watcher(**kwargs) -> LiveWatcher:
    """Start the background watcher thread and return it."""
    watcher = LiveWatcher(**kwargs)
    watcher.start()
    return watcher
