"""Tests for P1 generators: MCP skeleton, git hooks, eval harness."""

from __future__ import annotations

import pytest

from cruise_ai.recommendations.mcp_discovery import generate_mcp_skeleton, detect as mcp_detect
from cruise_ai.recommendations.hooks import (
    generate_git_hook,
    generate_build_hook,
    generate_pr_hook,
    detect as hooks_detect,
)
from cruise_ai.recommendations.eval_harness import (
    generate_eval_harness,
    detect as eval_detect,
)
from cruise_ai.recommendations.engine import recommend


# === MCP Skeleton Generation ===


class TestMCPSkeletonGeneration:
    def test_basic_skeleton(self):
        result = generate_mcp_skeleton("GitHub", ["/repos", "/users", "/issues"])
        assert result["filename"] == "mcp_server_github.py"
        assert "FastMCP" in result["content"]
        assert "repos" in result["content"]
        assert "users" in result["content"]
        assert "issues" in result["content"]
        assert "description" in result

    def test_skeleton_with_nested_endpoints(self):
        result = generate_mcp_skeleton("Stripe", ["/v1/charges", "/v1/customers/{id}"])
        assert result["filename"] == "mcp_server_stripe.py"
        assert "v1_charges" in result["content"]
        assert "v1_customers_id" in result["content"]
        assert "@mcp.tool()" in result["content"]

    def test_skeleton_empty_endpoints(self):
        result = generate_mcp_skeleton("Empty", [])
        assert result["filename"] == "mcp_server_empty.py"
        assert "placeholder" in result["content"]

    def test_skeleton_special_characters_in_name(self):
        result = generate_mcp_skeleton("My-Cool API", ["/test"])
        assert result["filename"] == "mcp_server_my_cool_api.py"
        assert "my_cool_api" in result["content"]

    def test_skeleton_has_run_block(self):
        result = generate_mcp_skeleton("test", ["/hello"])
        assert 'if __name__ == "__main__"' in result["content"]
        assert "mcp.run()" in result["content"]


# === MCP Detection with generate_mcp_skeleton action ===


class TestMCPDetectSkeletonRule:
    def test_detect_skeleton_when_acted_on_feedback(self):
        sessions = [
            {"commands": ["curl https://api.example.com/users"], "context_files": []}
            for _ in range(5)
        ]
        profile = {"tools_used": [], "total_sessions": 5}
        scan_results = {
            "mcps": [],
            "config_files": ["swagger.json"],
            "feedback_history": [
                {"action_type": "create_mcp_server", "action": "acted"}
            ],
        }
        recs = mcp_detect(sessions, profile, scan_results)
        skeleton_recs = [r for r in recs if r.action_type == "generate_mcp_skeleton"]
        assert len(skeleton_recs) >= 1
        assert skeleton_recs[0].confidence == 80
        assert skeleton_recs[0].trust_level == "observed"

    def test_no_skeleton_without_acted_feedback(self):
        sessions = [
            {"commands": ["curl https://api.example.com/users"], "context_files": []}
            for _ in range(5)
        ]
        profile = {"tools_used": [], "total_sessions": 5}
        scan_results = {
            "mcps": [],
            "config_files": ["swagger.json"],
            "feedback_history": [],
        }
        recs = mcp_detect(sessions, profile, scan_results)
        skeleton_recs = [r for r in recs if r.action_type == "generate_mcp_skeleton"]
        assert len(skeleton_recs) == 0


# === Git Hook Generation ===


class TestGitHookGeneration:
    def test_pre_commit_hook(self):
        result = generate_git_hook("pre-commit", ["pytest", "ruff check ."])
        assert result["filename"] == ".git/hooks/pre-commit"
        assert "#!/bin/sh" in result["content"]
        assert "pytest" in result["content"]
        assert "ruff check ." in result["content"]
        assert "exit 1" in result["content"]
        assert "set -e" in result["content"]

    def test_post_commit_hook(self):
        result = generate_git_hook("post-commit", ["echo done"])
        assert result["filename"] == ".git/hooks/post-commit"
        assert "echo done" in result["content"]

    def test_pre_push_hook(self):
        result = generate_git_hook("pre-push", ["npm test", "npm run build"])
        assert result["filename"] == ".git/hooks/pre-push"
        assert "npm test" in result["content"]
        assert "npm run build" in result["content"]
        assert "All pre-push checks passed" in result["content"]

    def test_invalid_hook_type_defaults_to_pre_commit(self):
        result = generate_git_hook("invalid-type", ["lint"])
        assert result["filename"] == ".git/hooks/pre-commit"

    def test_hook_error_handling_structure(self):
        result = generate_git_hook("pre-commit", ["mypy ."])
        # Each command should have error handling
        assert "if ! mypy ." in result["content"]
        assert "FAILED: mypy ." in result["content"]


# === Build Hook Generation ===


class TestBuildHookGeneration:
    def test_build_hook_basic(self):
        result = generate_build_hook(["npm install", "npm run build", "npm test"])
        assert result["filename"] == "scripts/build.sh"
        assert "#!/bin/sh" in result["content"]
        assert "npm install" in result["content"]
        assert "npm run build" in result["content"]
        assert "npm test" in result["content"]
        assert "Build Complete" in result["content"]

    def test_build_hook_description(self):
        result = generate_build_hook(["make", "make test"])
        assert "2 step(s)" in result["description"]


# === PR Hook Generation ===


class TestPRHookGeneration:
    def test_pr_hook_basic(self):
        result = generate_pr_hook(["npm test", "npm run lint"])
        assert result["filename"] == ".github/workflows/pr-checks.yml"
        assert "pull_request" in result["content"]
        assert "npm test" in result["content"]
        assert "npm run lint" in result["content"]
        assert "actions/checkout@v4" in result["content"]
        assert "ubuntu-latest" in result["content"]

    def test_pr_hook_description(self):
        result = generate_pr_hook(["pytest", "mypy", "ruff"])
        assert "3 check(s)" in result["description"]

    def test_pr_hook_empty_checks(self):
        result = generate_pr_hook([])
        assert result["filename"] == ".github/workflows/pr-checks.yml"
        assert "pull_request" in result["content"]


# === Eval Harness Detection ===


class TestEvalHarnessDetection:
    def test_detect_when_sessions_lack_tests(self):
        """If >30% of sessions have no test commands, recommend eval harness."""
        sessions = [
            {"commands": ["git commit -m 'fix'"], "context_files": ["src/app.py"]}
            for _ in range(8)
        ] + [
            {"commands": ["pytest"], "context_files": ["tests/test_app.py"]}
            for _ in range(2)
        ]
        profile = {"tools_used": [], "total_sessions": 10}
        scan_results = {"stack": ["python"], "config_files": ["pyproject.toml"]}

        recs = eval_detect(sessions, profile, scan_results)
        assert len(recs) >= 1
        assert recs[0].action_type == "create_eval_harness"
        assert recs[0].trust_level == "heuristic"
        assert 65 <= recs[0].confidence <= 72

    def test_no_detect_when_tests_present(self):
        """No recommendation when most sessions include tests."""
        sessions = [
            {"commands": ["pytest", "git commit"], "context_files": ["src/x.py"]}
            for _ in range(10)
        ]
        profile = {"tools_used": [], "total_sessions": 10}
        scan_results = {"stack": ["python"], "config_files": []}

        recs = eval_detect(sessions, profile, scan_results)
        assert len(recs) == 0

    def test_no_detect_few_sessions(self):
        """No recommendation with fewer than 3 sessions."""
        sessions = [{"commands": ["git commit"], "context_files": ["x.py"]}]
        profile = {"tools_used": [], "total_sessions": 1}
        scan_results = {}
        recs = eval_detect(sessions, profile, scan_results)
        assert len(recs) == 0


# === Eval Harness Generation ===


class TestEvalHarnessGeneration:
    def test_python_harness(self):
        result = generate_eval_harness("python", ["unit tests", "integration"])
        assert result["filename"] == "tests/test_eval_harness.py"
        assert "import pytest" in result["content"]
        assert "unit_tests" in result["content"]
        assert "integration" in result["content"]
        assert "def test_" in result["content"]

    def test_javascript_harness(self):
        result = generate_eval_harness("javascript", ["api response", "rendering"])
        assert result["filename"] == "tests/eval_harness.test.js"
        assert "describe(" in result["content"]
        assert "expect(" in result["content"]
        assert "api response" in result["content"]
        assert "rendering" in result["content"]

    def test_empty_patterns_generates_placeholder(self):
        result = generate_eval_harness("python", [])
        assert "placeholder" in result["content"]

    def test_unknown_language_defaults_to_python(self):
        result = generate_eval_harness("rust", ["test"])
        # Falls back to pytest since only python/js have templates
        assert result["filename"] == "tests/test_eval_harness.py"


# === Engine Integration ===


class TestEngineIntegration:
    def test_eval_harness_registered_in_engine(self):
        """Verify eval_harness detect is registered and runs through engine."""
        sessions = [
            {"commands": ["git push"], "context_files": ["main.py"]}
            for _ in range(10)
        ]
        profile = {"tools_used": [], "total_sessions": 10, "total_tokens": 5000}
        scan_results = {"stack": ["python"], "config_files": ["pyproject.toml"]}

        recs = recommend(sessions, profile, scan_results)
        eval_recs = [r for r in recs if r.category == "eval_harness"]
        assert len(eval_recs) >= 1
        assert eval_recs[0].action_type == "create_eval_harness"
