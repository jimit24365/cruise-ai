"""Tests for the opt-in code scan (code_intel), coverage report, and the
experimental Claude Desktop adapter.

Privacy invariants under test: metrics only (no file contents persisted),
opt-in gating, and code-scan evidence raising but never lowering buildDomain.
"""

import json

from cruise_ai.adapters.claude_desktop import ClaudeDesktopAdapter
from cruise_ai.aggregator import build_coverage_report
from cruise_ai.code_intel import scan_repo, scan_repos
from cruise_ai.consent import OPT_IN_ONLY_SOURCES, prompt_consent
from cruise_ai.scoring import compute_positioning


def make_repo(tmp_path, name="myrepo"):
    repo = tmp_path / name
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "app.py").write_text("\n".join(f"x{i} = {i}" for i in range(600)))
    (repo / "src" / "util.py").write_text("y = 1\n")
    (repo / "tests" / "test_app.py").write_text("def test_x():\n    assert True\n")
    (repo / "README.md").write_text("# myrepo\n")
    (repo / "Dockerfile").write_text("FROM python:3.12\n")
    (repo / "requirements.txt").write_text("anthropic>=0.40\nflask==3.0\n")
    return repo


class TestScanRepo:
    def test_metrics_only_no_content(self, tmp_path):
        repo = make_repo(tmp_path)
        result = scan_repo(str(repo))
        assert result is not None
        # No file content anywhere in the result
        dumped = json.dumps(result)
        assert "x1 = 1" not in dumped
        assert "FROM python" not in dumped
        # No dependency versions
        assert "0.40" not in dumped
        assert "3.0" not in dumped

    def test_structure_and_tests(self, tmp_path):
        result = scan_repo(str(make_repo(tmp_path)))
        assert result["filesByLang"]["Python"] == 3
        assert result["testFiles"] == 1
        assert result["hasReadme"] is True
        assert "Docker" in result["deployConfigs"]

    def test_hotspot_detected(self, tmp_path):
        result = scan_repo(str(make_repo(tmp_path)))
        hotspots = result["hotspots"]
        assert len(hotspots) == 1
        assert hotspots[0]["file"].endswith("app.py")
        assert hotspots[0]["lines"] >= 500

    def test_llm_sdk_detected_from_manifest(self, tmp_path):
        result = scan_repo(str(make_repo(tmp_path)))
        assert "Anthropic SDK" in result["llmSdks"]
        assert result["agentFrameworks"] == []

    def test_missing_path_returns_none(self, tmp_path):
        assert scan_repo(str(tmp_path / "nope")) is None

    def test_skips_vendored_dirs(self, tmp_path):
        repo = tmp_path / "r"
        (repo / "node_modules" / "dep").mkdir(parents=True)
        (repo / "node_modules" / "dep" / "index.js").write_text("x" * 100)
        (repo / "main.js").write_text("let a = 1\n")
        result = scan_repo(str(repo))
        assert result["sourceFiles"] == 1


class TestScanRepos:
    def test_cards_emitted_only_when_supported(self, tmp_path):
        repo = make_repo(tmp_path)
        result = scan_repos([str(repo)])
        labels = [c["label"] for c in result["codeIntelligence"]]
        assert "Refactor hotspot" in labels
        # Deploy config without CI → harness suggestion
        assert "Harness suggestion" in labels
        # Has README and < 20 source files → no doc/test gap cards
        assert "Doc gap" not in labels
        assert "Test gap" not in labels

    def test_empty_input_is_valid(self):
        result = scan_repos([])
        assert result["available"] is False
        assert result["codeIntelligence"] == []


class TestBuildDomainFromCodeScan:
    def _base(self):
        return {"mcpServerCount": 0, "planCount": 0, "maxParallelAgents": 0, "agentModeRatio": 0}

    def test_llm_sdk_raises_products_to_ai_products(self):
        ci = {"available": True, "llmSdks": ["Anthropic SDK"], "agentFrameworks": []}
        pos = compute_positioning(self._base(), git_data=None, code_intel=ci)
        assert pos["buildDomain"]["primary"] == "ai_products"
        assert any("(code scan)" in e for e in pos["buildDomain"]["evidence"])

    def test_agent_framework_raises_to_ai_systems(self):
        ci = {"available": True, "llmSdks": [], "agentFrameworks": ["CrewAI"]}
        pos = compute_positioning(self._base(), git_data=None, code_intel=ci)
        assert pos["buildDomain"]["primary"] == "ai_systems"

    def test_never_lowers_domain(self):
        git_data = {
            "projects": [
                {"frameworks": ["LangChain"], "tools": [], "languages": [], "commits_6m": 1}
            ]
        }
        ci = {"available": True, "llmSdks": ["OpenAI SDK"], "agentFrameworks": []}
        pos = compute_positioning(self._base(), git_data=git_data, code_intel=ci)
        assert pos["buildDomain"]["primary"] == "ai_systems"

    def test_no_code_intel_unchanged(self):
        pos = compute_positioning(self._base(), git_data=None, code_intel=None)
        assert pos["buildDomain"]["primary"] == "products"


class TestCoverageReport:
    def test_detected_but_unconsented_is_a_gap(self):
        coverage = build_coverage_report(
            enabled_sources={
                "claude_code": True,
                "cursor": False,
                "codex": True,
                "git": True,
                "claude_desktop": False,
            },
            collection_config={"window": "all", "repos": "all"},
            detected_sources={
                "claude_code": True,
                "cursor": True,
                "codex": False,
                "git": True,
                "claude_desktop": False,
            },
            raw_data={"claude_code": {"x": 1}, "cursor": None, "codex": None},
            git_data={"projects": []},
            code_scan_ran=True,
        )
        gap_sources = [g["source"] for g in coverage["gaps"]]
        assert "cursor" in gap_sources
        assert "codex" not in gap_sources  # not on machine → not a gap
        cursor_gap = next(g for g in coverage["gaps"] if g["source"] == "cursor")
        assert "calibrate" in cursor_gap["widen"]

    def test_window_and_repo_filters_are_gaps(self):
        coverage = build_coverage_report(
            enabled_sources={"git": True},
            collection_config={"window": 180, "repos": ["/a", "/b"]},
            detected_sources={"git": True},
            raw_data={},
            git_data={"projects": []},
            code_scan_ran=True,
        )
        gap_sources = [g["source"] for g in coverage["gaps"]]
        assert "window" in gap_sources
        assert "repos" in gap_sources

    def test_maximal_collection_is_complete(self):
        coverage = build_coverage_report(
            enabled_sources={
                k: True for k in ("claude_code", "cursor", "codex", "git", "claude_desktop")
            },
            collection_config={"window": "all", "repos": "all"},
            detected_sources={
                "claude_code": True,
                "cursor": True,
                "codex": True,
                "git": True,
                "claude_desktop": True,
            },
            raw_data={"claude_code": {}, "cursor": {}, "codex": {}, "claude_desktop": {}},
            git_data={"projects": []},
            code_scan_ran=True,
        )
        assert coverage["complete"] is True

    def test_code_scan_not_run_is_a_gap(self):
        coverage = build_coverage_report(
            enabled_sources={},
            collection_config={},
            detected_sources={},
            raw_data={},
            git_data=None,
            code_scan_ran=False,
        )
        assert any(g["source"] == "code_scan" for g in coverage["gaps"])


class TestClaudeDesktopAdapter:
    def test_not_detected_when_dir_missing(self, tmp_path):
        adapter = ClaudeDesktopAdapter(desktop_dir=tmp_path / "nope")
        assert adapter.detect() is False

    def test_reads_mcp_config_emits_no_sessions(self, tmp_path):
        desktop = tmp_path / "Claude"
        desktop.mkdir()
        (desktop / "claude_desktop_config.json").write_text(
            json.dumps(
                {"mcpServers": {"filesystem": {"command": "npx"}, "github": {"command": "npx"}}}
            )
        )
        adapter = ClaudeDesktopAdapter(desktop_dir=desktop)
        assert adapter.detect() is True
        sessions = adapter.scan()
        assert sessions == []  # honest: no transcripts exist locally
        raw = adapter.raw_data()
        assert raw["mcpServerCount"] == 2
        assert raw["fidelity"] == "low"
        assert raw["experimental"] is True

    def test_corrupt_config_safe(self, tmp_path):
        desktop = tmp_path / "Claude"
        desktop.mkdir()
        (desktop / "claude_desktop_config.json").write_text("{not json")
        adapter = ClaudeDesktopAdapter(desktop_dir=desktop)
        assert adapter.scan() == []
        assert adapter.raw_data()["mcpServerCount"] == 0


class TestConsentOptIn:
    def test_non_interactive_excludes_experimental_sources(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))
        sources = prompt_consent(non_interactive=True)
        assert sources["claude_code"] is True
        assert sources["git"] is True
        for key in OPT_IN_ONLY_SOURCES:
            # never enabled silently — but a prior explicit yes is
            # preserved (see test_yes_flag_preserves_prior_opt_in)
            assert sources[key] is False, f"{key} must never be enabled silently"
