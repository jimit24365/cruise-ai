"""Tests for CLI subcommands, collection config, and data collection (Steps 1-2)."""

import json
from pathlib import Path
from unittest.mock import patch

from cruise_ai.consent import (
    default_collection_config,
    load_collection_config,
    load_consent,
    save_collection_config,
    save_consent,
)

# ── Collection config tests ──────────────────────────────────────────────────


def test_collection_config_default_maximal():
    """Default collection config = all sources, all repos, all-time."""
    config = default_collection_config()
    assert config["window"] == "all"
    assert config["repos"] == "all"


def test_collection_config_save_load(tmp_path, monkeypatch):
    """Round-trip: save collection config then load it back."""
    monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))
    config = {"window": 30, "repos": "all"}
    save_collection_config(config)

    loaded = load_collection_config()
    assert loaded is not None
    assert loaded["window"] == 30
    assert loaded["repos"] == "all"
    assert "configured_at" in loaded


def test_collection_config_save_with_repo_list(tmp_path, monkeypatch):
    """Collection config with explicit repo list."""
    monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))
    config = {"window": 7, "repos": ["/home/user/project-a", "/home/user/project-b"]}
    save_collection_config(config)

    loaded = load_collection_config()
    assert loaded["window"] == 7
    assert loaded["repos"] == ["/home/user/project-a", "/home/user/project-b"]


def test_collection_config_load_returns_none_when_missing(tmp_path, monkeypatch):
    """load_collection_config returns None when no file exists."""
    monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))
    assert load_collection_config() is None


def test_collection_config_load_handles_corrupt_file(tmp_path, monkeypatch):
    """load_collection_config returns None for corrupt JSON."""
    monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "collection_config.json").write_text("not json")
    assert load_collection_config() is None


def test_prompt_collection_scope_non_interactive():
    """Non-interactive collection scope returns maximal defaults."""
    from cruise_ai.consent import prompt_collection_scope

    config = prompt_collection_scope(non_interactive=True)
    assert config["window"] == "all"
    assert config["repos"] == "all"


# ── Subcommand tests ─────────────────────────────────────────────────────────


def test_cmd_calibrate_writes_both_files(tmp_path, monkeypatch):
    """calibrate --yes writes both consent.json and collection_config.json."""
    monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))

    from cruise_ai.build_profile import cmd_calibrate

    class Args:
        yes = True

    cmd_calibrate(Args())

    consent = load_consent()
    assert consent is not None
    assert consent["sources"]["claude_code"] is True

    config = load_collection_config()
    assert config is not None
    assert config["window"] == "all"


def test_cmd_assess_auto_calibrates(tmp_path, monkeypatch):
    """assess with no consent auto-runs calibrate first."""
    monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))

    from cruise_ai.build_profile import _ensure_calibrated

    # No consent file exists yet
    assert load_consent() is None

    enabled = _ensure_calibrated(non_interactive=True)

    # Consent and config should now exist
    assert load_consent() is not None
    assert load_collection_config() is not None
    assert enabled["claude_code"] is True


def test_ensure_calibrated_creates_default_config_if_missing(tmp_path, monkeypatch):
    """If consent exists but collection_config doesn't, default config is created."""
    monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))

    # Create consent but no collection config
    save_consent({"claude_code": True, "cursor": True, "codex": True, "git": True})
    assert load_consent() is not None
    assert load_collection_config() is None

    from cruise_ai.build_profile import _ensure_calibrated

    _ensure_calibrated(non_interactive=True)

    config = load_collection_config()
    assert config is not None
    assert config["window"] == "all"


def test_cmd_enrich_generates_prompt(capsys, tmp_path, monkeypatch):
    """enrich subcommand generates enrichment prompt."""
    monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))

    save_consent({"claude_code": True, "cursor": True, "codex": True, "git": True})
    save_collection_config({"window": "all", "repos": "all"})

    from cruise_ai.paths import data_dir, profile_path

    data_dir()
    profile = {
        "schema_version": "1.0",
        "dimensions": {},
        "archetypes": [],
        "workMode": {"dominant": {"id": "Prompt-Iterate", "line": "Iterates"}, "secondary": []},
        "positioning": {
            "leverageMode": {"current": "prompting"},
            "buildDomain": {"primary": "products"},
            "techDomains": [],
        },
        "wrappedStats": {"tools": [], "models": []},
        "growthEdge": {"suggestion": "test", "context": "test"},
        "assessment": {"sessions": 0},
        "tools_detected": [],
    }
    with open(profile_path(), "w") as f:
        json.dump(profile, f)

    monkeypatch.setattr(
        "cruise_ai.adapters._registry.get_session_adapters",
        lambda: [],
    )

    class FakeGit:
        name = "git"

        def scan_projects(self, *a, **k):
            return None

        def raw_data(self):
            return None

    monkeypatch.setattr(
        "cruise_ai.adapters._registry.get_git_adapter",
        lambda: FakeGit(),
    )

    from cruise_ai.build_profile import cmd_enrich

    class Args:
        submit = None
        key = None
        yes = True

    cmd_enrich(Args())
    output = capsys.readouterr().out
    assert "enrich" in output.lower()
    assert "next steps" in output.lower()


# ── Honest progress messages ─────────────────────────────────────────────────


def test_print_signal_insights_with_data(capsys):
    """Signal insights print real metrics, not fabricated praise."""
    from cruise_ai.build_profile import _print_signal_insights

    scan_results = {
        "tools_detected": ["claude_code", "cursor_ide"],
        "summary": {
            "total_sessions": 50,
            "total_projects": 10,
            "total_plans": 5,
            "ai_usage_span_days": 30,
        },
        "normalized": {
            "toolCallRatio": 0.7,
            "totalToolCalls": 200,
            "avgPromptWordCount": 45,
        },
        "activityByDay": [
            {"date": "2025-01-01", "sessions": 1},
            {"date": "2025-01-02", "sessions": 2},
            {"date": "2025-01-03", "commits": 3},
            {"date": "2025-01-04", "sessions": 1},
            {"date": "2025-01-05", "sessions": 1},
        ],
    }

    _print_signal_insights(scan_results)
    output = capsys.readouterr().out

    # Real metrics present
    assert "10 repos" in output
    assert "50 sessions" in output
    assert "2 tools" in output
    assert "30 days" in output
    # Streak detected
    assert "5-day streak" in output
    # Agent-heavy
    assert "200 tool calls" in output
    # Prompt complexity
    assert "45 words/prompt" in output
    # Planning
    assert "5 architecture plans" in output


def test_print_signal_insights_thin_data(capsys):
    """Thin data produces honest warning, not fabricated praise."""
    from cruise_ai.build_profile import _print_signal_insights

    scan_results = {
        "tools_detected": ["claude_code"],
        "summary": {
            "total_sessions": 2,
            "total_projects": 1,
            "ai_usage_span_days": 3,
        },
        "normalized": {},
        "activityByDay": [],
    }

    _print_signal_insights(scan_results)
    output = capsys.readouterr().out

    assert "Limited data" in output
    assert "2 sessions" in output
    assert "Confidence will be low" in output


def test_print_signal_insights_no_streak(capsys):
    """Non-consecutive days don't claim a streak."""
    from cruise_ai.build_profile import _print_signal_insights

    scan_results = {
        "tools_detected": ["claude_code"],
        "summary": {
            "total_sessions": 20,
            "total_projects": 5,
            "ai_usage_span_days": 60,
        },
        "normalized": {},
        "activityByDay": [
            {"date": "2025-01-01"},
            {"date": "2025-01-10"},
            {"date": "2025-01-20"},
        ],
    }

    _print_signal_insights(scan_results)
    output = capsys.readouterr().out

    assert "streak" not in output


# ── Longest streak helper ────────────────────────────────────────────────────


def test_longest_streak_empty():
    from cruise_ai.build_profile import _longest_streak

    assert _longest_streak([]) == 0


def test_longest_streak_consecutive():
    from cruise_ai.build_profile import _longest_streak

    activity = [
        {"date": "2025-01-01", "sessions": 2},
        {"date": "2025-01-02", "sessions": 1},
        {"date": "2025-01-03", "commits": 4},
        {"date": "2025-01-04", "sessions": 0},
        {"date": "2025-01-05", "sessions": 1},
        {"date": "2025-01-06", "sessions": 1},
    ]
    # Padding days (no sessions, no commits) break the streak
    assert _longest_streak(activity) == 3


def test_longest_streak_single_day():
    from cruise_ai.build_profile import _longest_streak

    assert _longest_streak([{"date": "2025-06-01", "sessions": 1}]) == 1
    # A padded zero-activity day is not a streak
    assert _longest_streak([{"date": "2025-06-01", "sessions": 0}]) == 0


# ── Legacy flag routing ─────────────────────────────────────────────────────


def test_main_parses_calibrate_subcommand():
    """argparse recognizes 'calibrate' subcommand."""
    from cruise_ai.build_profile import main

    with patch("sys.argv", ["cruise_ai", "calibrate", "--yes"]):
        with patch("cruise_ai.build_profile.cmd_calibrate") as mock_cal:
            main()
            mock_cal.assert_called_once()
            args = mock_cal.call_args[0][0]
            assert args.command == "calibrate"
            assert args.yes is True


def test_main_parses_assess_subcommand():
    """argparse recognizes 'assess' subcommand."""
    from cruise_ai.build_profile import main

    with patch("sys.argv", ["cruise_ai", "assess", "--rescan"]):
        with patch("cruise_ai.build_profile.cmd_assess") as mock_assess:
            main()
            mock_assess.assert_called_once()
            args = mock_assess.call_args[0][0]
            assert args.command == "assess"
            assert args.rescan is True


def test_main_parses_report_subcommand():
    """argparse recognizes 'report' subcommand."""
    from cruise_ai.build_profile import main

    with patch("sys.argv", ["cruise_ai", "report", "--port", "8080"]):
        with patch("cruise_ai.build_profile.cmd_report") as mock_report:
            main()
            mock_report.assert_called_once()
            args = mock_report.call_args[0][0]
            assert args.command == "report"
            assert args.port == 8080


def test_main_parses_enrich_subcommand():
    """argparse recognizes 'enrich' subcommand."""
    from cruise_ai.build_profile import main

    with patch("sys.argv", ["cruise_ai", "enrich"]):
        with patch("cruise_ai.build_profile.cmd_enrich") as mock_enrich:
            main()
            mock_enrich.assert_called_once()


def test_legacy_preview_flag():
    """--preview flag routes to show_preview."""

    with patch("sys.argv", ["cruise_ai", "--preview"]):
        with patch("cruise_ai.build_profile.show_preview") as mock_preview:
            with patch("cruise_ai.build_profile._handle_legacy", wraps=None) as _:
                # Need to patch _handle_legacy to avoid actual imports
                pass

    # Simpler approach: test _handle_legacy directly
    from cruise_ai.build_profile import _handle_legacy

    class Args:
        tools = False
        reset_consent = False
        preview = True
        serve = False
        yes = False
        rescan = False
        project = None
        port = 7749

    with patch("cruise_ai.build_profile.show_preview") as mock_preview:
        with patch("cruise_ai.paths.data_dir"):
            _handle_legacy(Args())
            mock_preview.assert_called_once()


def test_legacy_tools_flag():
    """--tools flag routes to list_tools."""
    from cruise_ai.build_profile import _handle_legacy

    class Args:
        tools = True
        reset_consent = False
        preview = False
        serve = False
        yes = False
        rescan = False
        project = None
        port = 7749

    with patch("cruise_ai.scanner.list_tools") as mock_tools:
        with patch("cruise_ai.paths.data_dir"):
            _handle_legacy(Args())
            mock_tools.assert_called_once()


def test_legacy_serve_flag_runs_assess_then_report():
    """--serve flag runs assess then report."""
    from cruise_ai.build_profile import _handle_legacy

    class Args:
        tools = False
        reset_consent = False
        preview = False
        serve = True
        yes = True
        rescan = False
        project = None
        port = 7749

    with patch("cruise_ai.build_profile.cmd_assess") as mock_assess:
        with patch("cruise_ai.build_profile.cmd_report") as mock_report:
            with patch("cruise_ai.paths.data_dir"):
                _handle_legacy(Args())
                mock_assess.assert_called_once()
                mock_report.assert_called_once()


# ── collection_config_path exists ────────────────────────────────────────────


def test_collection_config_path_exists():
    """collection_config_path is available from paths module."""
    from cruise_ai.paths import collection_config_path

    p = collection_config_path()
    assert p.name == "collection_config.json"
    assert "data" in str(p)


# ── Step 2: Git auto-discovery tests ─────────────────────────────────────────


class TestGitAutoDiscovery:
    """Tests for GitAdapter._discover_repos and _walk_for_git."""

    def test_discover_repos_finds_git_dirs(self, tmp_path, monkeypatch):
        """Auto-discovery finds directories containing .git/."""
        from cruise_ai.adapters.git import GitAdapter

        # Create fake repos under tmp_path
        repo_a = tmp_path / "code" / "project-a"
        (repo_a / ".git").mkdir(parents=True)
        repo_b = tmp_path / "code" / "project-b"
        (repo_b / ".git").mkdir(parents=True)
        # Non-repo dir
        (tmp_path / "code" / "not-a-repo").mkdir(parents=True)

        adapter = GitAdapter()

        # Patch _COMMON_ROOTS to only use our tmp_path
        import cruise_ai.adapters.git as git_mod

        monkeypatch.setattr(git_mod, "_COMMON_ROOTS", [tmp_path / "code"])

        # Also patch Path.cwd to avoid scanning real filesystem
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path / "nonexistent")

        repos = adapter._discover_repos(max_depth=3)
        repo_names = {r.name for r in repos}

        assert "project-a" in repo_names
        assert "project-b" in repo_names
        assert "not-a-repo" not in repo_names

    def test_discover_repos_respects_depth_limit(self, tmp_path, monkeypatch):
        """Repos deeper than max_depth are not found."""
        from cruise_ai.adapters.git import GitAdapter

        # Create a deep repo: tmp_path/a/b/c/d/deep-repo/.git (depth=5)
        deep = tmp_path / "a" / "b" / "c" / "d" / "deep-repo"
        (deep / ".git").mkdir(parents=True)
        # Shallow repo: tmp_path/a/shallow-repo/.git (depth=2)
        shallow = tmp_path / "a" / "shallow-repo"
        (shallow / ".git").mkdir(parents=True)

        import cruise_ai.adapters.git as git_mod

        monkeypatch.setattr(git_mod, "_COMMON_ROOTS", [tmp_path])
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path / "nonexistent")

        adapter = GitAdapter()
        repos = adapter._discover_repos(max_depth=3)
        repo_names = {r.name for r in repos}

        assert "shallow-repo" in repo_names
        assert "deep-repo" not in repo_names

    def test_discover_repos_skips_dotdirs(self, tmp_path, monkeypatch):
        """Directories starting with '.' are skipped during discovery."""
        from cruise_ai.adapters.git import GitAdapter

        hidden = tmp_path / ".hidden" / "secret-repo"
        (hidden / ".git").mkdir(parents=True)
        visible = tmp_path / "visible-repo"
        (visible / ".git").mkdir(parents=True)

        import cruise_ai.adapters.git as git_mod

        monkeypatch.setattr(git_mod, "_COMMON_ROOTS", [tmp_path])
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path / "nonexistent")

        adapter = GitAdapter()
        repos = adapter._discover_repos(max_depth=3)
        repo_names = {r.name for r in repos}

        assert "visible-repo" in repo_names
        assert "secret-repo" not in repo_names


# ── Step 2: Git window tests ─────────────────────────────────────────────────


class TestGitWindow:
    """Tests for window parameter in scan_projects."""

    def test_window_all_no_since(self, tmp_path, monkeypatch):
        """window='all' should not include --since in git commands."""
        from cruise_ai.adapters.git import GitAdapter

        repo = tmp_path / "my-repo"
        (repo / ".git").mkdir(parents=True)

        calls = []

        def fake_git_run(args, cwd=None, timeout=15):
            calls.append(args)
            return ""

        import cruise_ai.adapters.git as git_mod

        monkeypatch.setattr(git_mod, "git_run", fake_git_run)
        monkeypatch.setattr(
            git_mod,
            "detect_tech_stack",
            lambda p: {
                "languages": [],
                "frameworks": [],
                "tools": [],
            },
        )
        monkeypatch.setattr(git_mod, "_COMMON_ROOTS", [])
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path / "nonexistent")

        adapter = GitAdapter()
        adapter.scan_projects([str(repo)], window="all")

        # No --since should appear in any call
        for call_args in calls:
            for arg in call_args:
                assert "--since" not in arg, f"Found --since in: {call_args}"

    def test_window_30_days_since(self, tmp_path, monkeypatch):
        """window=30 should include --since=30 days ago."""
        from cruise_ai.adapters.git import GitAdapter

        repo = tmp_path / "my-repo"
        (repo / ".git").mkdir(parents=True)

        calls = []

        def fake_git_run(args, cwd=None, timeout=15):
            calls.append(args)
            return ""

        import cruise_ai.adapters.git as git_mod

        monkeypatch.setattr(git_mod, "git_run", fake_git_run)
        monkeypatch.setattr(
            git_mod,
            "detect_tech_stack",
            lambda p: {
                "languages": [],
                "frameworks": [],
                "tools": [],
            },
        )
        monkeypatch.setattr(git_mod, "_COMMON_ROOTS", [])
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path / "nonexistent")

        adapter = GitAdapter()
        adapter.scan_projects([str(repo)], window=30)

        # Should have --since=30 days ago
        found_since = False
        for call_args in calls:
            for arg in call_args:
                if "--since=30 days ago" in arg:
                    found_since = True
        assert found_since, f"Expected --since=30 days ago in calls: {calls}"

    def test_window_none_defaults_to_6_months(self, tmp_path, monkeypatch):
        """window=None should use legacy --since=6 months ago."""
        from cruise_ai.adapters.git import GitAdapter

        repo = tmp_path / "my-repo"
        (repo / ".git").mkdir(parents=True)

        calls = []

        def fake_git_run(args, cwd=None, timeout=15):
            calls.append(args)
            return ""

        import cruise_ai.adapters.git as git_mod

        monkeypatch.setattr(git_mod, "git_run", fake_git_run)
        monkeypatch.setattr(
            git_mod,
            "detect_tech_stack",
            lambda p: {
                "languages": [],
                "frameworks": [],
                "tools": [],
            },
        )
        monkeypatch.setattr(git_mod, "_COMMON_ROOTS", [])
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path / "nonexistent")

        adapter = GitAdapter()
        adapter.scan_projects([str(repo)], window=None)

        found_since = False
        for call_args in calls:
            for arg in call_args:
                if "--since=6 months ago" in arg:
                    found_since = True
        assert found_since, f"Expected --since=6 months ago in calls: {calls}"


# ── Step 2: Git repo_filter tests ────────────────────────────────────────────


def test_git_repo_filter(tmp_path, monkeypatch):
    """repo_filter limits scanning to matching repos only."""
    from cruise_ai.adapters.git import GitAdapter

    repo_a = tmp_path / "repo-a"
    (repo_a / ".git").mkdir(parents=True)
    repo_b = tmp_path / "repo-b"
    (repo_b / ".git").mkdir(parents=True)

    scanned = []

    def fake_git_run(args, cwd=None, timeout=15):
        scanned.append(str(cwd))
        return ""

    import cruise_ai.adapters.git as git_mod

    monkeypatch.setattr(git_mod, "git_run", fake_git_run)
    monkeypatch.setattr(
        git_mod,
        "detect_tech_stack",
        lambda p: {
            "languages": [],
            "frameworks": [],
            "tools": [],
        },
    )
    monkeypatch.setattr(git_mod, "_COMMON_ROOTS", [])
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path / "nonexistent")

    adapter = GitAdapter()
    adapter.scan_projects(
        [str(repo_a), str(repo_b)],
        window="all",
        repo_filter=[str(repo_a)],
    )

    # Only repo_a should have been scanned
    assert any("repo-a" in s for s in scanned)
    assert not any("repo-b" in s for s in scanned)


# ── Step 2: commit_dates in output ───────────────────────────────────────────


def test_git_commit_dates_in_output(tmp_path, monkeypatch):
    """scan_projects returns commit_dates in each project dict."""
    from cruise_ai.adapters.git import GitAdapter

    repo = tmp_path / "my-repo"
    (repo / ".git").mkdir(parents=True)

    call_count = [0]

    def fake_git_run(args, cwd=None, timeout=15):
        call_count[0] += 1
        if "--format=%aI" in args:
            return "2026-06-01T10:00:00+00:00\n2026-06-02T11:00:00+00:00"
        if "--oneline" in args:
            return "abc123 feat: first\ndef456 fix: second"
        return ""

    import cruise_ai.adapters.git as git_mod

    monkeypatch.setattr(git_mod, "git_run", fake_git_run)
    monkeypatch.setattr(
        git_mod,
        "detect_tech_stack",
        lambda p: {
            "languages": ["Python"],
            "frameworks": [],
            "tools": [],
        },
    )
    monkeypatch.setattr(git_mod, "_COMMON_ROOTS", [])
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path / "nonexistent")

    adapter = GitAdapter()
    result = adapter.scan_projects([str(repo)], window="all")

    assert result is not None
    projects = result["projects"]
    assert len(projects) == 1
    assert "commit_dates" in projects[0]
    assert len(projects[0]["commit_dates"]) == 2
    assert "2026-06-01" in projects[0]["commit_dates"][0]


# ── Step 2: run_adapters passes collection_config ────────────────────────────


def test_run_adapters_passes_collection_config(monkeypatch):
    """collection_config flows from run_adapters to GitAdapter.scan_projects."""
    from cruise_ai.adapters._registry import run_adapters

    captured = {}

    class MockGitAdapter:
        name = "git"

        def detect(self):
            return True

        def scan_projects(self, project_paths, **kwargs):
            captured.update(kwargs)
            return None

        def raw_data(self):
            return None

    # Disable session adapters so we only test git flow
    monkeypatch.setattr(
        "cruise_ai.adapters._registry.get_session_adapters",
        lambda: [],
    )
    monkeypatch.setattr(
        "cruise_ai.adapters._registry.get_git_adapter",
        lambda: MockGitAdapter(),
    )

    config = {"window": 30, "repos": ["/path/to/repo"]}
    run_adapters(
        enabled_sources={"git": True},
        collection_config=config,
    )

    assert captured.get("window") == 30
    assert captured.get("repo_filter") == ["/path/to/repo"]


def test_run_adapters_repos_all_means_no_filter(monkeypatch):
    """repos='all' in collection_config means repo_filter=None."""
    from cruise_ai.adapters._registry import run_adapters

    captured = {}

    class MockGitAdapter:
        name = "git"

        def detect(self):
            return True

        def scan_projects(self, project_paths, **kwargs):
            captured.update(kwargs)
            return None

        def raw_data(self):
            return None

    monkeypatch.setattr(
        "cruise_ai.adapters._registry.get_session_adapters",
        lambda: [],
    )
    monkeypatch.setattr(
        "cruise_ai.adapters._registry.get_git_adapter",
        lambda: MockGitAdapter(),
    )

    config = {"window": "all", "repos": "all"}
    run_adapters(
        enabled_sources={"git": True},
        collection_config=config,
    )

    assert captured.get("window") == "all"
    assert captured.get("repo_filter") is None


# ── Step 2: sources subcommand ───────────────────────────────────────────────


def test_sources_subcommand_registered():
    """argparse recognizes 'sources' subcommand."""
    from cruise_ai.build_profile import main

    with patch("sys.argv", ["cruise_ai", "sources", "--yes"]):
        with patch("cruise_ai.build_profile.cmd_sources") as mock_sources:
            main()
            mock_sources.assert_called_once()
            args = mock_sources.call_args[0][0]
            assert args.command == "sources"
            assert args.yes is True


def test_sources_subcommand_output(tmp_path, monkeypatch, capsys):
    """cmd_sources prints discovered source summary."""
    monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))

    # Pre-create consent and config
    save_consent({"claude_code": True, "cursor": False, "codex": True, "git": True})
    save_collection_config({"window": "all", "repos": "all"})

    # Mock session adapters
    class FakeAdapter:
        def __init__(self, name, detected, sessions=None, raw=None):
            self._name = name
            self._detected = detected
            self._sessions = sessions or []
            self._raw = raw

        @property
        def name(self):
            return self._name

        def detect(self):
            return self._detected

        def scan(self, project_filter=None):
            return self._sessions

        def raw_data(self):
            return self._raw

    fake_adapters = [
        FakeAdapter(
            "claude_code",
            True,
            raw={
                "total_sessions": 14,
                "earliest": "2026-05-10T00:00:00Z",
                "latest": "2026-06-08T00:00:00Z",
            },
        ),
        FakeAdapter("cursor", False),
        FakeAdapter(
            "codex",
            True,
            raw={
                "total_sessions": 3,
                "path": str(tmp_path / ".codex" / "sessions"),
                "earliest": "2026-06-01T00:00:00Z",
                "latest": "2026-06-07T00:00:00Z",
            },
        ),
    ]

    monkeypatch.setattr(
        "cruise_ai.adapters._registry.get_session_adapters",
        lambda: fake_adapters,
    )

    class MockGitAdapter:
        name = "git"

        def detect(self):
            return True

        def scan_projects(self, project_paths, **kwargs):
            return {
                "projects": [],
                "auto_discovered_repos": 18,
                "session_derived_repos": 5,
                "total_repos": 22,
                "window": "all",
            }

        def raw_data(self):
            return None

    monkeypatch.setattr(
        "cruise_ai.adapters._registry.get_git_adapter",
        lambda: MockGitAdapter(),
    )

    from cruise_ai.build_profile import cmd_sources

    class Args:
        yes = True

    cmd_sources(Args())
    output = capsys.readouterr().out

    assert "Discovered Sources" in output
    assert "Claude Code" in output
    assert "COLLECTED" in output
    assert "DISABLED" in output or "NOT FOUND" in output  # cursor disabled
    assert "Collection Config" in output
    assert "all" in output


# ── Step 2: codex date_range ─────────────────────────────────────────────────


def test_codex_raw_data_has_date_range(tmp_path, monkeypatch):
    """Codex adapter raw_data includes earliest/latest timestamps."""
    sessions_dir = tmp_path / ".codex" / "sessions"
    sessions_dir.mkdir(parents=True)

    # Write a minimal JSONL session
    session_file = sessions_dir / "test_session.jsonl"
    import json as _json

    lines = [
        _json.dumps(
            {"type": "message", "role": "user", "content": "hello", "created_at": 1717200000}
        ),
        _json.dumps(
            {"type": "message", "role": "assistant", "content": "hi", "created_at": 1717300000}
        ),
    ]
    session_file.write_text("\n".join(lines))

    from cruise_ai.adapters.codex import CodexAdapter

    adapter = CodexAdapter(sessions_dir=sessions_dir)
    adapter.scan()
    raw = adapter.raw_data()

    assert raw is not None
    assert "earliest" in raw
    assert "latest" in raw
    assert raw["earliest"] is not None
    assert raw["latest"] is not None


# ── Step 2: git raw_data metadata ────────────────────────────────────────────


def test_git_raw_data_includes_metadata(tmp_path, monkeypatch):
    """Git raw_data includes auto_discovered_repos, session_derived_repos, window."""
    from cruise_ai.adapters.git import GitAdapter

    repo = tmp_path / "my-repo"
    (repo / ".git").mkdir(parents=True)

    import cruise_ai.adapters.git as git_mod

    monkeypatch.setattr(git_mod, "git_run", lambda args, cwd=None, timeout=15: "")
    monkeypatch.setattr(
        git_mod,
        "detect_tech_stack",
        lambda p: {
            "languages": [],
            "frameworks": [],
            "tools": [],
        },
    )
    monkeypatch.setattr(git_mod, "_COMMON_ROOTS", [])
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path / "nonexistent")

    adapter = GitAdapter()
    result = adapter.scan_projects([str(repo)], window="all")

    assert result is not None
    assert "auto_discovered_repos" in result
    assert "session_derived_repos" in result
    assert "total_repos" in result
    assert result["window"] == "all"


# ── E2E smoke test: full pipeline ────────────────────────────────────────────


class TestE2ESmokeTest:
    """End-to-end smoke: assess → profile/report data → shareable → privacy."""

    def _make_sessions(self):
        """Build a minimal list of Session objects for the pipeline."""
        from cruise_ai.adapters._base import Session

        sessions = []
        for i in range(5):
            s = Session(
                tool="claude_code",
                session_id=f"sess-{i}",
                project_path=f"/home/user/proj{i}",
                user_msgs=10 + i,
                assistant_msgs=10 + i,
                models=["claude-sonnet-4-20250514"],
                tool_calls_by_type={"Read": 5, "Edit": 3, "Bash": 2},
                prompt_word_counts=[40, 60, 80],
            )
            sessions.append(s)
        return sessions

    def _make_raw_data(self):
        return {
            "claude_code": {
                "total_sessions": 5,
                "total_messages": 100,
                "models_used": {"claude-sonnet-4-20250514": 5},
                "tool_calls": 50,
                "earliest": "2026-01-01T00:00:00Z",
                "latest": "2026-06-08T00:00:00Z",
            },
            "cursor": None,
            "codex": None,
        }

    def _make_git_data(self):
        return {
            "projects": [
                {
                    "name": "myproject",
                    "path": "/home/user/myproject",
                    "commits_6m": 42,
                    "stack": {
                        "languages": ["Python", "TypeScript"],
                        "frameworks": ["Flask"],
                        "tools": ["pytest"],
                    },
                    "languages": {"Python": 200, "TypeScript": 100},
                    "frameworks": ["Flask"],
                    "tools": ["pytest"],
                    "commit_dates": ["2026-06-01", "2026-06-02"],
                }
            ],
            "total_repos": 1,
        }

    def test_full_pipeline_assess_produces_valid_profile(self, tmp_path, monkeypatch):
        """Assess pipeline produces a valid scan result then a scored profile."""
        from cruise_ai.build_profile import run_scan
        from cruise_ai.scoring import score_profile

        sessions = self._make_sessions()
        raw_data = self._make_raw_data()
        git_data = self._make_git_data()

        with patch(
            "cruise_ai.adapters._registry.run_adapters",
            return_value=(sessions, raw_data, git_data),
        ):
            with patch(
                "cruise_ai.aggregator.build_experimental_signals",
                return_value={"available": False, "signals": [], "codeIntelligence": []},
            ):
                scan_result = run_scan()

        assert scan_result is not None
        assert "normalized" in scan_result
        assert "tools_detected" in scan_result

        # Score the profile
        profile = score_profile(scan_result)

        # Core fields exist
        assert "composite" in profile
        assert "dimensions" in profile
        assert "archetypes" in profile
        assert isinstance(profile["composite"], (int, float))
        assert profile["composite"] >= 0

        # Dimensions have scores and evidence
        for _dim_id, dim in profile["dimensions"].items():
            if isinstance(dim, dict):
                assert "score" in dim
                assert "evidence" in dim
                assert isinstance(dim["evidence"], list)

        # Archetypes have scores and evidence
        for arch in profile["archetypes"]:
            assert "score" in arch
            assert "evidence" in arch
            assert isinstance(arch["evidence"], list)

        # Positioning exists
        assert "positioning" in profile
        pos = profile["positioning"]
        assert "leverageMode" in pos
        assert "buildDomain" in pos
        assert "techDomains" in pos

    def test_shareable_profile_has_no_private_data(self, tmp_path, monkeypatch):
        """Shareable profile must exclude private fields."""
        from cruise_ai.build_profile import run_scan
        from cruise_ai.schema import build_shareable_profile
        from cruise_ai.scoring import score_profile

        sessions = self._make_sessions()
        raw_data = self._make_raw_data()
        git_data = self._make_git_data()

        with patch(
            "cruise_ai.adapters._registry.run_adapters",
            return_value=(sessions, raw_data, git_data),
        ):
            with patch(
                "cruise_ai.aggregator.build_experimental_signals",
                return_value={"available": False, "signals": [], "codeIntelligence": []},
            ):
                scan_result = run_scan()

        profile = score_profile(scan_result)

        # Add private data that should be stripped
        profile["growthEdge"] = {"suggestion": "test", "context": "test"}
        profile["antiPatterns"] = [{"id": "test", "name": "test", "icon": "!", "risk": "test"}]
        profile["experimental"] = {
            "available": True,
            "signals": [{"label": "test"}],
            "codeIntelligence": [],
        }
        profile["enrichment"] = {
            "narrative": "Test narrative",
            "strengths": [{"claim": "Test", "evidence": "Test"}],
            "growthAreas": [{"observed": "Private growth", "nextSignal": "Private signal"}],
            "whatYouBuilt": ["Built things"],
            "decisionPatterns": {"style": "Test"},
            "howYouUseAI": {"persona": "Builder", "line": "Test"},
        }
        profile["wrappedStats"] = profile.get("wrappedStats", {})
        profile["wrappedStats"]["goToPrompt"] = "my secret prompt"

        shareable = build_shareable_profile(profile)

        # Private fields must be absent
        assert "growthEdge" not in shareable, "growthEdge leaked into shareable"
        assert "antiPatterns" not in shareable, "antiPatterns leaked into shareable"
        assert "experimental" not in shareable, "experimental leaked into shareable"

        # goToPrompt must be scrubbed from wrappedStats
        ws = shareable.get("wrappedStats", {})
        assert "goToPrompt" not in ws, "goToPrompt leaked into shareable wrappedStats"

        # growthAreas must be scrubbed from enrichment
        enr = shareable.get("enrichment", {})
        assert "growthAreas" not in enr, "growthAreas leaked into shareable enrichment"

        # But other enrichment fields should survive
        assert enr.get("narrative") == "Test narrative"
        assert enr.get("strengths") is not None
        assert len(enr["strengths"]) > 0

    def test_enrichment_heuristic_fallback(self, tmp_path, monkeypatch):
        """Heuristic enrichment produces valid six-block structure."""
        from cruise_ai.build_profile import run_scan
        from cruise_ai.enrichment import build_heuristic_enrichment, validate_enrichment
        from cruise_ai.scoring import score_profile

        sessions = self._make_sessions()
        raw_data = self._make_raw_data()
        git_data = self._make_git_data()

        with patch(
            "cruise_ai.adapters._registry.run_adapters",
            return_value=(sessions, raw_data, git_data),
        ):
            with patch(
                "cruise_ai.aggregator.build_experimental_signals",
                return_value={"available": False, "signals": [], "codeIntelligence": []},
            ):
                scan_result = run_scan()

        profile = score_profile(scan_result)
        enrichment = build_heuristic_enrichment(profile)

        # Validate the six-block structure
        valid, error = validate_enrichment(enrichment)
        assert valid, f"Heuristic enrichment invalid: {error}"

        # All six blocks present
        assert "narrative" in enrichment
        assert "whatYouBuilt" in enrichment
        assert "decisionPatterns" in enrichment
        assert "strengths" in enrichment
        assert "growthAreas" in enrichment
        assert "howYouUseAI" in enrichment

    def test_no_banned_strings_in_codebase(self):
        """No banned strings remain in output-facing code."""
        import os

        banned_patterns = ["IDE telemetry"]
        code_dirs = [
            Path(__file__).parent.parent / "cruise_ai" / "static",
        ]

        for code_dir in code_dirs:
            if not code_dir.exists():
                continue
            for root, _dirs, files in os.walk(code_dir):
                for f in files:
                    if f.endswith((".html", ".js", ".css")):
                        content = (Path(root) / f).read_text()
                        for banned in banned_patterns:
                            assert banned not in content, (
                                f"Banned string '{banned}' found in {Path(root) / f}"
                            )

    def test_no_file_paths_in_shareable_json(self, tmp_path, monkeypatch):
        """Shareable JSON must not contain filesystem paths."""
        from cruise_ai.build_profile import run_scan
        from cruise_ai.schema import build_shareable_profile
        from cruise_ai.scoring import score_profile

        sessions = self._make_sessions()
        raw_data = self._make_raw_data()
        git_data = self._make_git_data()

        with patch(
            "cruise_ai.adapters._registry.run_adapters",
            return_value=(sessions, raw_data, git_data),
        ):
            with patch(
                "cruise_ai.aggregator.build_experimental_signals",
                return_value={"available": False, "signals": [], "codeIntelligence": []},
            ):
                scan_result = run_scan()

        profile = score_profile(scan_result)
        shareable = build_shareable_profile(profile)
        shareable_json = json.dumps(shareable)

        # No absolute paths should appear
        assert "/home/user/" not in shareable_json, "Filesystem path leaked into shareable JSON"


class TestCommandUX:
    """Regression tests from the full-command UX audit."""

    def test_assess_project_rejects_missing_path(self, capsys, monkeypatch, tmp_path):
        monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))
        from cruise_ai.build_profile import cmd_assess

        class Args:
            yes = True
            rescan = False
            project = "/tmp/definitely-not-a-real-path-xyz"
            code = False

        cmd_assess(Args())
        out = capsys.readouterr().out
        assert "project path not found" in out

    def test_guard_hints_are_clone_adaptive(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))
        import pytest as _pytest

        from cruise_ai.export import export_static
        from cruise_ai.paths import cli_invocation

        with _pytest.raises(RuntimeError) as exc:
            export_static(tmp_path / "out")
        # The hint must be the invocation that works on this machine
        assert cli_invocation() in str(exc.value)

    def test_scanner_quiet_by_default(self, monkeypatch, capsys):
        monkeypatch.delenv("CRUISE_AI_VERBOSE", raising=False)
        from cruise_ai.scanner import log

        log("should not appear")
        assert "[scanner]" not in capsys.readouterr().err

    def test_scanner_verbose_when_enabled(self, monkeypatch, capsys):
        monkeypatch.setenv("CRUISE_AI_VERBOSE", "1")
        from cruise_ai.scanner import log

        log("should appear")
        assert "[scanner] should appear" in capsys.readouterr().err
