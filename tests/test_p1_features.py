"""Tests for cruise_ai.recommendations P1 features."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from cruise_ai.recommendations.engine import recommend
from cruise_ai.recommendations.types import Recommendation, CONFIDENCE_THRESHOLD
from cruise_ai.recommendations import token_optimization, mcp_discovery, hooks, skills


# ─── Fixtures ────────────────────────────────────────────────────────────────


@dataclass
class FakeSession:
    """Minimal Session-like object for tests."""

    tool: str = "kiro"
    session_id: str = "abc"
    project_path: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    user_msgs: int = 5
    assistant_msgs: int = 5
    tool_calls_by_type: dict = field(default_factory=dict)
    models: list = field(default_factory=list)
    prompt_word_counts: list = field(default_factory=list)
    context_files: list = field(default_factory=list)
    commands: list = field(default_factory=list)
    extras: dict = field(default_factory=dict)


def _make_session(**kwargs) -> FakeSession:
    """Create a FakeSession with sensible defaults."""
    import uuid

    defaults = {
        "session_id": str(uuid.uuid4()),
        "tool": "kiro",
        "user_msgs": 5,
        "prompt_word_counts": [30, 25, 20],
        "models": ["claude-sonnet-4-6"],
        "tool_calls_by_type": {"read": 3, "write": 2},
        "project_path": "/home/user/project",
        "started_at": datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
        "context_files": [],
        "commands": [],
    }
    defaults.update(kwargs)
    return FakeSession(**defaults)


# ─── Prompt Compression Tests ────────────────────────────────────────────────


class TestPromptCompression:
    """Tests for the prompt compression detector."""

    def test_no_recommendation_below_threshold(self):
        """No recommendation when avg prompt length <= 500 words."""
        sessions = [_make_session(prompt_word_counts=[100, 200, 300]) for _ in range(10)]
        recs = token_optimization._detect_prompt_compression(sessions)
        assert recs == []

    def test_recommends_above_500_avg(self):
        """Recommend summarization when avg prompt length > 500 words."""
        sessions = [_make_session(prompt_word_counts=[600, 700, 800]) for _ in range(10)]
        recs = token_optimization._detect_prompt_compression(sessions)
        assert len(recs) == 1
        assert recs[0].action_type == "enable_prompt_compression"
        assert recs[0].trust_level == "observed"
        assert recs[0].confidence >= 60

    def test_high_priority_for_very_long(self):
        """High priority when avg exceeds 800 words."""
        sessions = [_make_session(prompt_word_counts=[900, 1000, 1100]) for _ in range(10)]
        recs = token_optimization._detect_prompt_compression(sessions)
        assert len(recs) == 1
        assert recs[0].priority == "high"

    def test_empty_sessions_no_crash(self):
        """Empty sessions don't crash."""
        recs = token_optimization._detect_prompt_compression([])
        assert recs == []


# ─── Cached Context Tests ────────────────────────────────────────────────────


class TestCachedContext:
    """Tests for the cached context detector."""

    def test_no_recommendation_with_few_sessions(self):
        """No recommendation with < 4 sessions."""
        sessions = [_make_session(context_files=["a.py", "b.py"]) for _ in range(3)]
        recs = token_optimization._detect_cached_context(sessions)
        assert recs == []

    def test_recommends_when_files_repeated(self):
        """Recommend pinning when same files appear in >3 sessions."""
        sessions = [
            _make_session(context_files=["config.py", "utils.py", "main.py"])
            for _ in range(6)
        ]
        recs = token_optimization._detect_cached_context(sessions)
        assert len(recs) == 1
        assert recs[0].action_type == "pin_context_files"
        assert recs[0].trust_level == "observed"
        assert recs[0].confidence >= 60

    def test_no_recommendation_unique_files(self):
        """No recommendation when files are unique across sessions."""
        sessions = [
            _make_session(context_files=[f"file_{i}.py"])
            for i in range(10)
        ]
        recs = token_optimization._detect_cached_context(sessions)
        assert recs == []

    def test_handles_dict_sessions(self):
        """Works with dict-style sessions (no getattr)."""
        sessions = [
            {"context_files": ["shared.py", "common.py"]}
            for _ in range(5)
        ]
        # Should not crash — may not detect since no getattr support for other fields
        recs = token_optimization._detect_cached_context(sessions)
        # Just verify no crash
        assert isinstance(recs, list)


# ─── Token Waste Score Tests ─────────────────────────────────────────────────


class TestTokenWasteScore:
    """Tests for the token waste score computation."""

    def test_low_score_no_recommendation(self):
        """No recommendation when waste score < 30."""
        sessions = [_make_session(prompt_word_counts=[50, 60, 70]) for _ in range(10)]
        recs = token_optimization._compute_token_waste_score(sessions, {})
        assert recs == []

    def test_high_score_produces_recommendation(self):
        """Recommendation when multiple waste factors are present."""
        sessions = [
            _make_session(
                prompt_word_counts=[600, 700, 800],
                context_files=["same.py", "repeated.py"],
                models=["claude-opus-4"],
            )
            for _ in range(15)
        ]
        recs = token_optimization._compute_token_waste_score(sessions, {})
        assert len(recs) == 1
        assert recs[0].action_type == "reduce_token_waste"
        assert "waste" in recs[0].headline.lower() or "score" in recs[0].headline.lower()

    def test_too_few_sessions(self):
        """No recommendation with < 5 sessions."""
        sessions = [_make_session() for _ in range(3)]
        recs = token_optimization._compute_token_waste_score(sessions, {})
        assert recs == []


# ─── MCP Discovery Tests ─────────────────────────────────────────────────────


class TestMCPDiscovery:
    """Tests for the MCP discovery detector."""

    def test_no_recommendation_without_api_patterns(self):
        """No recommendation when no API patterns found."""
        sessions = [_make_session() for _ in range(5)]
        scan_results = {"mcps": [], "config_files": ["package.json"], "skills": []}
        recs = mcp_discovery.detect(sessions, {}, scan_results)
        assert recs == []

    def test_recommends_mcp_for_swagger_file(self):
        """Recommend MCP when swagger file found but no MCPs configured."""
        sessions = [_make_session() for _ in range(5)]
        scan_results = {
            "mcps": [],
            "config_files": ["swagger.json", "package.json"],
            "skills": [],
        }
        recs = mcp_discovery.detect(sessions, {}, scan_results)
        assert len(recs) >= 1
        assert any(r.action_type == "create_mcp_server" for r in recs)
        assert all(r.trust_level == "heuristic" for r in recs)

    def test_recommends_mcp_for_api_calls_in_sessions(self):
        """Recommend MCP when curl/fetch patterns found in commands."""
        sessions = [
            _make_session(commands=[
                "curl https://api.example.com/users",
                "curl https://api.example.com/posts",
                "curl https://api.example.com/comments",
                "curl https://api.example.com/auth/login",
            ])
            for _ in range(3)
        ]
        scan_results = {"mcps": [], "config_files": [], "skills": []}
        recs = mcp_discovery.detect(sessions, {}, scan_results)
        assert len(recs) >= 1
        mcp_recs = [r for r in recs if r.action_type == "create_mcp_server"]
        assert len(mcp_recs) >= 1
        assert mcp_recs[0].confidence >= 60

    def test_no_recommendation_when_mcps_exist(self):
        """No recommendation when MCPs are already configured."""
        sessions = [
            _make_session(commands=["curl https://api.example.com/users"])
            for _ in range(5)
        ]
        scan_results = {
            "mcps": ["existing-mcp-server"],
            "config_files": ["swagger.json"],
            "skills": [],
        }
        recs = mcp_discovery.detect(sessions, {}, scan_results)
        assert recs == []

    def test_teach_text_explains_mcp(self):
        """teach_text should explain what an MCP is."""
        sessions = [_make_session() for _ in range(5)]
        scan_results = {
            "mcps": [],
            "config_files": ["openapi.yaml"],
            "skills": [],
        }
        recs = mcp_discovery.detect(sessions, {}, scan_results)
        assert len(recs) >= 1
        assert "MCP" in recs[0].teach_text
        assert len(recs[0].teach_text) > 50


# ─── Hooks Tests ─────────────────────────────────────────────────────────────


class TestHooks:
    """Tests for the hooks detector."""

    def test_no_recommendation_with_few_sessions(self):
        """No recommendation with < 5 sessions."""
        sessions = [_make_session(commands=["git commit", "git push"]) for _ in range(3)]
        recs = hooks.detect(sessions, {}, {})
        assert recs == []

    def test_detects_git_commit_push_pattern(self):
        """Detect git commit + push repeated > 5 times."""
        sessions = [
            _make_session(commands=["git add .", "git commit -m 'fix'", "git push"])
            for _ in range(8)
        ]
        recs = hooks.detect(sessions, {}, {})
        git_recs = [r for r in recs if r.action_type == "create_git_hook"]
        assert len(git_recs) >= 1
        assert git_recs[0].trust_level == "observed"
        assert git_recs[0].confidence >= 60

    def test_detects_test_lint_pattern(self):
        """Detect test + lint repeated > 5 times."""
        sessions = [
            _make_session(commands=["pytest", "flake8", "mypy"])
            for _ in range(8)
        ]
        recs = hooks.detect(sessions, {}, {})
        hook_recs = [r for r in recs if "hook" in r.action_type]
        assert len(hook_recs) >= 1

    def test_teach_text_explains_hooks(self):
        """teach_text should explain hook benefits."""
        sessions = [
            _make_session(commands=["git commit -m 'x'", "git push origin main"])
            for _ in range(10)
        ]
        recs = hooks.detect(sessions, {}, {})
        if recs:
            assert "hook" in recs[0].teach_text.lower() or "automat" in recs[0].teach_text.lower()

    def test_no_crash_empty_commands(self):
        """Sessions with no commands don't crash."""
        sessions = [_make_session(commands=[]) for _ in range(10)]
        recs = hooks.detect(sessions, {}, {})
        assert isinstance(recs, list)


# ─── Skills Revision & Health Tests ──────────────────────────────────────────


class TestSkillRevision:
    """Tests for skill revision detector."""

    def test_no_recommendation_without_stale_skills(self):
        """No recommendation when skills are fresh."""
        sessions = [_make_session() for _ in range(10)]
        scan_results = {
            "skills": [{"name": "angular", "modified_days_ago": 5}],
            "mcps": [],
            "config_files": [],
        }
        recs = skills._detect_skill_revision(sessions, scan_results)
        assert recs == []

    def test_recommends_revision_for_stale_skills(self):
        """Recommend revision when skills >30 days old."""
        sessions = [_make_session(tool_calls_by_type={"read": 5, "jest": 3}) for _ in range(10)]
        scan_results = {
            "skills": [
                {"name": "testing-patterns", "modified_days_ago": 45},
                {"name": "ci-workflow", "modified_days_ago": 60},
            ],
            "mcps": [],
            "config_files": [],
        }
        recs = skills._detect_skill_revision(sessions, scan_results)
        assert len(recs) == 1
        assert recs[0].action_type == "revise_skill"
        assert recs[0].trust_level == "heuristic"
        assert recs[0].confidence >= 60


class TestSkillHealth:
    """Tests for skill health detector."""

    def test_no_recommendation_without_skills(self):
        """No recommendation when no skills configured."""
        sessions = [_make_session() for _ in range(10)]
        scan_results = {"skills": [], "mcps": [], "config_files": []}
        recs = skills._detect_skill_health(sessions, scan_results)
        assert recs == []

    def test_recommends_cleanup_for_unreferenced_skills(self):
        """Recommend cleanup when skills exist but aren't in session context."""
        sessions = [
            _make_session(context_files=["src/main.py", "tests/test_main.py"])
            for _ in range(10)
        ]
        scan_results = {
            "skills": [
                {"name": "old-workflow", "path": ".kiro/skills/old-workflow/SKILL.md"},
                {"name": "deprecated-patterns", "path": ".kiro/skills/deprecated/SKILL.md"},
            ],
            "mcps": [],
            "config_files": [],
        }
        recs = skills._detect_skill_health(sessions, scan_results)
        assert len(recs) == 1
        assert recs[0].action_type == "cleanup_skills"
        assert recs[0].trust_level == "heuristic"

    def test_no_recommendation_when_skills_referenced(self):
        """No recommendation when skills are referenced in sessions."""
        sessions = [
            _make_session(context_files=[".kiro/skills/my-skill/SKILL.md"])
            for _ in range(10)
        ]
        scan_results = {
            "skills": [{"name": "my-skill", "path": ".kiro/skills/my-skill/SKILL.md"}],
            "mcps": [],
            "config_files": [],
        }
        recs = skills._detect_skill_health(sessions, scan_results)
        assert recs == []


# ─── Engine Integration Tests ────────────────────────────────────────────────


class TestEngineIntegration:
    """Test that new detectors integrate properly with engine.recommend()."""

    def test_engine_runs_mcp_detector(self):
        """Engine runs MCP discovery and includes results."""
        sessions = [_make_session() for _ in range(5)]
        scan_results = {
            "mcps": [],
            "config_files": ["openapi.json"],
            "skills": [],
            "hooks": [],
        }
        recs = recommend(sessions, {}, scan_results)
        mcp_recs = [r for r in recs if r.category == "mcp_discovery"]
        assert len(mcp_recs) >= 1

    def test_engine_runs_hooks_detector(self):
        """Engine runs hooks detector and includes results."""
        sessions = [
            _make_session(commands=["git add .", "git commit -m 'fix'", "git push"])
            for _ in range(8)
        ]
        recs = recommend(sessions, {}, {"mcps": [], "config_files": [], "skills": [], "hooks": []})
        hook_recs = [r for r in recs if r.category == "hooks"]
        assert len(hook_recs) >= 1

    def test_engine_confidence_gate_filters_low_confidence(self):
        """Engine filters out recommendations below confidence threshold."""
        sessions = [_make_session() for _ in range(5)]
        recs = recommend(sessions, {}, {"mcps": [], "config_files": [], "skills": [], "hooks": []})
        for rec in recs:
            assert rec.confidence >= CONFIDENCE_THRESHOLD

    def test_engine_never_crashes_on_bad_input(self):
        """Engine returns empty list for unusual input, never crashes."""
        assert recommend([], None, None) == []
        assert recommend([], {}, {}) == []
        assert isinstance(recommend([None], {}, {}), list)
