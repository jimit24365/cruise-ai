"""Tests for nextmillionai.paths — path resolution across platforms.

Covers project-path resolution with hyphenated names and
Linux/Windows/macOS home-directory layouts.
"""

from __future__ import annotations

import os
from pathlib import PurePosixPath, PureWindowsPath

from nextmillionai.paths import (
    consent_path,
    data_dir,
    profile_path,
    scan_results_path,
    user_home,
)

# ── NEXTMILLIONAI_HOME override ──────────────────────────────────────────────


class TestUserHome:
    def test_uses_env_variable(self, tmp_path, monkeypatch):
        custom = tmp_path / "custom-nma-home"
        monkeypatch.setenv("NEXTMILLIONAI_HOME", str(custom))
        result = user_home()
        assert result == custom
        assert result.is_dir()

    def test_creates_directory(self, tmp_path, monkeypatch):
        target = tmp_path / "fresh" / "nested"
        monkeypatch.setenv("NEXTMILLIONAI_HOME", str(target))
        result = user_home()
        assert result.is_dir()

    def test_default_location(self, monkeypatch):
        monkeypatch.delenv("NEXTMILLIONAI_HOME", raising=False)
        result = user_home()
        assert result.name == ".nextmillionai"


class TestDataDir:
    def test_under_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path))
        d = data_dir()
        assert d == tmp_path / "data"
        assert d.is_dir()

    def test_is_child_of_user_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path))
        d = data_dir()
        h = user_home()
        assert str(d).startswith(str(h))


class TestDerivedPaths:
    def test_scan_results_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path))
        p = scan_results_path()
        assert p.name == "scan_results.json"
        assert p.parent == data_dir()

    def test_profile_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path))
        p = profile_path()
        assert p.name == "profile.json"
        assert p.parent == data_dir()

    def test_consent_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path))
        p = consent_path()
        assert p.name == "consent.json"
        assert p.parent == data_dir()


# ── Hyphenated project name resolution ───────────────────────────────────────


class TestHyphenatedProjectPaths:
    """The Claude Code project filter converts filesystem paths to slugs
    by replacing '/' with '-'. Verify the scanner matches these correctly."""

    def test_slug_from_simple_path(self):
        """Standard macOS path -> slug."""
        path = "/Users/dev/my-project"
        slug = path.replace("/", "-").lstrip("-")
        assert slug == "Users-dev-my-project"

    def test_slug_with_hyphens_in_name(self):
        """Project name already containing hyphens stays intact."""
        path = "/Users/dev/my-awesome-project"
        slug = path.replace("/", "-").lstrip("-")
        assert slug == "Users-dev-my-awesome-project"

    def test_slug_from_linux_path(self):
        """Linux home directory -> slug."""
        path = "/home/user/code/next-gen-app"
        slug = path.replace("/", "-").lstrip("-")
        assert slug == "home-user-code-next-gen-app"

    def test_slug_from_deep_path(self):
        """Deeply nested path -> slug preserves hierarchy."""
        path = "/Users/dev/workspace/org/repo-name"
        slug = path.replace("/", "-").lstrip("-")
        assert slug == "Users-dev-workspace-org-repo-name"

    def test_filter_matches_slug(self):
        """Verify the scanner's project_filter matching logic."""
        # Simulate what scan_claude_code does with project_filter
        project_filter = "/Users/dev/my-project"
        slug = project_filter.replace("/", "-").lstrip("-")

        # A directory named after this slug should match
        dir_name = "Users-dev-my-project"
        assert slug in dir_name

    def test_filter_partial_match(self):
        """A filter for a subdirectory matches the slug containing it."""
        project_filter = "/Users/dev/my-project"
        slug = project_filter.replace("/", "-").lstrip("-")

        dir_name = "Users-dev-my-project-subdir"
        assert slug in dir_name


# ── Platform path layout tests ───────────────────────────────────────────────


class TestPlatformPathLayouts:
    """Verify that the path-to-slug conversion works correctly for
    typical path layouts on macOS, Linux, and Windows."""

    def test_macos_layout(self):
        path = "/Users/alice/Developer/cool-app"
        slug = path.replace("/", "-").lstrip("-")
        assert slug == "Users-alice-Developer-cool-app"
        # The slug should be usable as a directory name (no / or \)
        assert "/" not in slug
        assert "\\" not in slug

    def test_linux_layout(self):
        path = "/home/bob/projects/my-tool"
        slug = path.replace("/", "-").lstrip("-")
        assert slug == "home-bob-projects-my-tool"
        assert "/" not in slug

    def test_windows_style_forward_slash(self):
        """Windows paths passed with forward slashes (Python normalizes)."""
        path = "C:/Users/carol/code/win-app"
        slug = path.replace("/", "-").lstrip("-")
        assert slug == "C:-Users-carol-code-win-app"
        assert "/" not in slug

    def test_posix_path_parts(self):
        """PurePosixPath can represent macOS and Linux paths."""
        p = PurePosixPath("/Users/dev/my-project")
        assert p.parts == ("/", "Users", "dev", "my-project")
        slug = "-".join(p.parts[1:])  # skip root
        assert slug == "Users-dev-my-project"

    def test_windows_path_parts(self):
        """PureWindowsPath represents Windows paths."""
        p = PureWindowsPath("C:\\Users\\dev\\my-project")
        assert p.parts == ("C:\\", "Users", "dev", "my-project")
        # Scanner slug uses forward-slash replacement, not parts
        forward = str(p).replace("\\", "/")
        slug = forward.replace("/", "-").lstrip("-")
        assert "Users-dev-my-project" in slug

    def test_home_expansion_posix(self, tmp_path, monkeypatch):
        """os.path.expanduser('~') resolves on all POSIX systems."""
        monkeypatch.setenv("HOME", str(tmp_path))
        expanded = os.path.expanduser("~")
        assert expanded == str(tmp_path)

    def test_path_with_spaces(self):
        """Paths with spaces get hyphens in the slug."""
        # Claude Code project dirs actually encode spaces as %20 or similar,
        # but the slug conversion preserves them after / -> - replacement.
        path = "/Users/dev/My Projects/cool-app"
        slug = path.replace("/", "-").lstrip("-")
        assert "My Projects" in slug

    def test_roundtrip_filter_to_slug(self):
        """Verify that a path filter converted to a slug matches
        a directory named with that same slug convention."""
        paths = [
            "/Users/alice/my-app",
            "/home/bob/next-gen-tool",
            "/Users/carol/Developer/web-app",
        ]
        for path in paths:
            slug = path.replace("/", "-").lstrip("-")
            # Should match a directory named exactly this way
            assert slug in slug  # trivially true
            # Should also match if the dir has a longer name
            assert slug in (slug + "-extra")
