"""Tests for the adapter registry and orchestration."""

from __future__ import annotations

import shutil
from pathlib import Path

from nextmillionai.adapters._registry import (
    get_git_adapter,
    get_session_adapters,
    run_adapters,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestGetAdapters:
    def test_session_adapters_returned(self):
        adapters = get_session_adapters()
        names = [a.name for a in adapters]
        # 4 first-class + 8 wider-field (other_tools group), order stable
        assert len(adapters) >= 12
        assert "claude_code" in names
        assert "cursor" in names
        assert "codex" in names
        assert "claude_desktop" in names  # experimental, consent default OFF
        for wider in (
            "aider",
            "cline",
            "continue",
            "copilot_chat",
            "windsurf",
            "zed_ai",
            "jetbrains_ai",
            "cody",
        ):
            assert wider in names

    def test_git_adapter_returned(self):
        adapter = get_git_adapter()
        assert adapter.name == "git"
        assert adapter.detect() is True


class TestConsentGating:
    def test_disabled_source_not_scanned(self, tmp_path):
        """When a source is disabled, its adapter is not run."""
        projects_dir = tmp_path / ".claude" / "projects"
        proj_dir = projects_dir / "-Users-dev-test"
        proj_dir.mkdir(parents=True)
        shutil.copy(FIXTURES / "sample_session.jsonl", proj_dir / "s.jsonl")

        # Disable claude_code — should get no sessions
        sessions, raw, git_data = run_adapters(
            enabled_sources={
                "claude_code": False,
                "cursor": False,
                "codex": False,
                "git": False,
            },
        )
        assert len(sessions) == 0
        assert raw.get("claude_code") is None
        assert raw.get("cursor") is None
        assert raw.get("codex") is None
        assert git_data is None

    def test_enabled_source_scanned(self, tmp_path, monkeypatch):
        """When a source is enabled and detected, its adapter runs."""
        import nextmillionai.scanner as scanner_mod

        projects_dir = tmp_path / ".claude" / "projects"
        proj_dir = projects_dir / "-Users-dev-test"
        proj_dir.mkdir(parents=True)
        shutil.copy(FIXTURES / "sample_session.jsonl", proj_dir / "s.jsonl")
        monkeypatch.setattr(scanner_mod, "CLAUDE_PROJECTS_DIR", projects_dir)

        sessions, raw, git_data = run_adapters(
            enabled_sources={
                "claude_code": True,
                "cursor": False,
                "codex": False,
                "git": False,
            },
        )
        assert len(sessions) > 0
        assert raw["claude_code"] is not None


class TestProjectPathCollection:
    def test_project_paths_from_sessions(self, tmp_path, monkeypatch):
        """run_adapters should collect project paths from sessions."""
        import nextmillionai.scanner as scanner_mod

        projects_dir = tmp_path / ".claude" / "projects"
        proj_dir = projects_dir / "-Users-dev-test"
        proj_dir.mkdir(parents=True)
        shutil.copy(FIXTURES / "sample_session.jsonl", proj_dir / "s.jsonl")
        monkeypatch.setattr(scanner_mod, "CLAUDE_PROJECTS_DIR", projects_dir)

        sessions, raw, _ = run_adapters(
            enabled_sources={
                "claude_code": True,
                "cursor": False,
                "codex": False,
                "git": False,
            },
        )
        paths = {s.project_path for s in sessions}
        assert "/Users/dev/my-project" in paths
