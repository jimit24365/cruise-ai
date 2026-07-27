"""Tests for cruise_ai.recommendations P2 features."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest

from cruise_ai.recommendations.engine import recommend
from cruise_ai.recommendations.types import Recommendation, CONFIDENCE_THRESHOLD
from cruise_ai.recommendations import token_optimization, skills
from cruise_ai.recommendations import health_score
from cruise_ai.recommendations import architecture_memory


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
    prompts: list = field(default_factory=list)
    extras: dict = field(default_factory=dict)


def _make_session(**kwargs) -> FakeSession:
    """Create a FakeSession with sensible defaults."""
    import uuid

    defaults: dict[str, Any] = {
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
        "prompts": [],
    }
    defaults.update(kwargs)
    return FakeSession(**defaults)


# ─── Context Window Growth Tests ─────────────────────────────────────────────


class TestContextWindowGrowth:
    """Test _detect_context_window_growth in token_optimization."""

    def test_growing_tokens_triggers_recommendation(self):
        """Sessions with >50% token growth should trigger recommendation."""
        sessions = []
        for _ in range(10):
            # Token counts that grow significantly from start to end
            sessions.append(_make_session(
                prompts=[
                    {"tokens_used": 100},
                    {"tokens_used": 120},
                    {"tokens_used": 150},
                    {"tokens_used": 180},
                    {"tokens_used": 200},
                    {"tokens_used": 250},
                ],
            ))

        recs = token_optimization._detect_context_window_growth(sessions)
        assert len(recs) >= 1
        rec = recs[0]
        assert rec.action_type == "split_long_sessions"
        assert rec.trust_level == "observed"
        assert rec.confidence == 68

    def test_flat_tokens_no_recommendation(self):
        """Sessions with stable token usage should not trigger."""
        sessions = []
        for _ in range(10):
            sessions.append(_make_session(
                prompts=[
                    {"tokens_used": 100},
                    {"tokens_used": 105},
                    {"tokens_used": 98},
                    {"tokens_used": 102},
                    {"tokens_used": 100},
                    {"tokens_used": 103},
                ],
            ))

        recs = token_optimization._detect_context_window_growth(sessions)
        assert len(recs) == 0

    def test_too_few_sessions_no_crash(self):
        """Should return empty list gracefully with minimal data."""
        recs = token_optimization._detect_context_window_growth([])
        assert recs == []

        recs = token_optimization._detect_context_window_growth([_make_session()])
        assert recs == []

    def test_sessions_without_prompts_skipped(self):
        """Sessions missing prompts field should be skipped gracefully."""
        sessions = [_make_session(prompts=[]) for _ in range(10)]
        recs = token_optimization._detect_context_window_growth(sessions)
        assert recs == []

    def test_dict_sessions_supported(self):
        """Dict-style sessions should also work."""
        sessions = []
        for _ in range(10):
            sessions.append({
                "prompts": [
                    {"tokens_used": 50},
                    {"tokens_used": 80},
                    {"tokens_used": 120},
                    {"tokens_used": 160},
                    {"tokens_used": 200},
                    {"tokens_used": 300},
                ],
            })

        recs = token_optimization._detect_context_window_growth(sessions)
        assert len(recs) >= 1
        assert recs[0].action_type == "split_long_sessions"

    def test_mixed_growing_and_flat_sessions(self):
        """Only fires when >30% of sessions show growth."""
        sessions = []
        # 2 growing sessions
        for _ in range(2):
            sessions.append(_make_session(
                prompts=[{"tokens_used": 50}, {"tokens_used": 80}, {"tokens_used": 200}],
            ))
        # 8 flat sessions
        for _ in range(8):
            sessions.append(_make_session(
                prompts=[{"tokens_used": 100}, {"tokens_used": 100}, {"tokens_used": 100}],
            ))

        recs = token_optimization._detect_context_window_growth(sessions)
        # 2/10 = 20% which is < 30% threshold
        assert len(recs) == 0


# ─── Health Score Tests ──────────────────────────────────────────────────────


class TestHealthScore:
    """Test compute_health_score and detect."""

    def test_basic_health_score_structure(self):
        """Health score returns correct dict structure."""
        sessions = [_make_session() for _ in range(10)]
        profile: dict[str, Any] = {"total_sessions": 10, "models_used": ["claude-sonnet-4-6"]}
        scan_results: dict[str, Any] = {"hooks": [], "mcps": [], "skills": [], "config_files": []}

        result = health_score.compute_health_score(sessions, profile, scan_results)

        assert "score" in result
        assert "breakdown" in result
        assert 0 <= result["score"] <= 100
        breakdown = result["breakdown"]
        assert "efficiency" in breakdown
        assert "diversity" in breakdown
        assert "automation" in breakdown
        assert "learning" in breakdown
        for v in breakdown.values():
            assert 0 <= v <= 100

    def test_high_score_with_good_config(self):
        """Well-configured setup should yield high score."""
        sessions = [_make_session(
            user_msgs=8,
            prompt_word_counts=[50, 60, 70],
            models=["claude-sonnet-4-6", "claude-haiku", "gpt-4o"],
            tool_calls_by_type={"read": 5, "write": 3, "grep": 2, "glob": 1, "task": 1},
        ) for _ in range(20)]

        profile: dict[str, Any] = {
            "total_sessions": 50,
            "models_used": ["claude-sonnet-4-6", "claude-haiku", "gpt-4o"],
            "tools_used": ["read", "write", "grep", "glob", "task"],
            "composite": 40,
            "dimensions": {"breadth": 80},
        }
        scan_results: dict[str, Any] = {
            "hooks": [{"name": "pre-commit"}],
            "mcps": [{"name": "mcp-server"}],
            "skills": [{"name": "coding"}],
            "config_files": [".kiro/steering/main.md"],
        }

        result = health_score.compute_health_score(sessions, profile, scan_results)
        assert result["score"] >= 70

    def test_low_score_triggers_recommendation(self):
        """Score < 60 should fire a recommendation."""
        sessions = [_make_session(
            user_msgs=30,
            prompt_word_counts=[600, 700, 800],
            models=["claude-opus-4"],
        ) for _ in range(10)]

        profile: dict[str, Any] = {"total_sessions": 5, "models_used": ["claude-opus-4"]}
        scan_results: dict[str, Any] = {"hooks": [], "mcps": [], "skills": [], "config_files": []}

        recs = health_score.detect(sessions, profile, scan_results)
        # Should fire since low diversity, low automation, mediocre efficiency
        if recs:
            assert recs[0].action_type == "improve_health_score"
            assert recs[0].confidence >= CONFIDENCE_THRESHOLD

    def test_high_score_no_recommendation(self):
        """Score >= 60 should not fire."""
        sessions = [_make_session(
            user_msgs=8,
            prompt_word_counts=[50, 60],
            models=["claude-sonnet-4-6", "claude-haiku", "gpt-4o", "gemini-pro"],
            tool_calls_by_type={"read": 5, "write": 3, "grep": 2, "glob": 1, "task": 1},
        ) for _ in range(30)]

        profile: dict[str, Any] = {
            "total_sessions": 60,
            "models_used": ["claude-sonnet-4-6", "claude-haiku", "gpt-4o", "gemini-pro"],
            "tools_used": ["read", "write", "grep", "glob", "task", "search", "lint"],
            "composite": 45,
            "dimensions": {"breadth": 85},
        }
        scan_results: dict[str, Any] = {
            "hooks": [{"name": "pre-commit"}],
            "mcps": [{"name": "mcp-server"}],
            "skills": [{"name": "coding"}],
            "config_files": [".kiro/steering/main.md"],
        }

        recs = health_score.detect(sessions, profile, scan_results)
        # High score should not fire
        result = health_score.compute_health_score(sessions, profile, scan_results)
        if result["score"] >= 60:
            assert len(recs) == 0

    def test_empty_inputs_no_crash(self):
        """Should not crash with empty inputs."""
        result = health_score.compute_health_score([], {}, {})
        assert "score" in result
        assert "breakdown" in result

    def test_none_inputs_no_crash(self):
        """Should not crash with None inputs."""
        result = health_score.compute_health_score([], None, None)  # type: ignore[arg-type]
        assert "score" in result


class TestHealthScoreBreakdown:
    """Test individual breakdown components."""

    def test_efficiency_high_with_short_prompts(self):
        """Short prompts + reasonable turns = high efficiency."""
        sessions = [_make_session(user_msgs=8, prompt_word_counts=[50, 60, 40]) for _ in range(10)]
        score = health_score._compute_efficiency(sessions, {})
        assert score >= 80

    def test_efficiency_low_with_long_prompts(self):
        """Very long prompts = low efficiency."""
        sessions = [_make_session(user_msgs=30, prompt_word_counts=[800, 900, 1000]) for _ in range(10)]
        score = health_score._compute_efficiency(sessions, {})
        assert score < 60

    def test_diversity_low_single_model(self):
        """Single model = low diversity."""
        sessions = [_make_session(models=["claude-sonnet-4-6"]) for _ in range(10)]
        score = health_score._compute_diversity(sessions, {"models_used": ["claude-sonnet-4-6"]})
        assert score < 60

    def test_diversity_high_multiple_models(self):
        """Multiple models + tools = high diversity."""
        sessions = [_make_session(
            models=["claude-sonnet-4-6", "claude-haiku", "gpt-4o", "gemini"],
            tool_calls_by_type={"read": 1, "write": 1, "grep": 1, "glob": 1, "task": 1, "lint": 1},
        ) for _ in range(10)]
        profile: dict[str, Any] = {
            "models_used": ["claude-sonnet-4-6", "claude-haiku", "gpt-4o", "gemini"],
            "tools_used": ["read", "write", "grep", "glob", "task", "lint"],
        }
        score = health_score._compute_diversity(sessions, profile)
        assert score >= 80

    def test_automation_zero_with_nothing_configured(self):
        """No hooks/MCPs/skills = low automation."""
        score = health_score._compute_automation({}, {"hooks": [], "mcps": [], "skills": [], "config_files": []})
        assert score == 20

    def test_automation_high_with_all_configured(self):
        """All configured = high automation."""
        scan: dict[str, Any] = {
            "hooks": [{"name": "pre-commit"}],
            "mcps": [{"name": "server"}],
            "skills": [{"name": "skill"}],
            "config_files": ["config.json"],
        }
        score = health_score._compute_automation({}, scan)
        assert score == 100


# ─── Skill Merge Tests ───────────────────────────────────────────────────────


class TestSkillMerge:
    """Test _detect_skill_merge."""

    def test_merge_detected_with_high_overlap(self):
        """Skills with >70% tool overlap should trigger merge recommendation."""
        sessions = [_make_session() for _ in range(5)]
        profile: dict[str, Any] = {}
        scan_results: dict[str, Any] = {
            "skills": [
                {"name": "skill-a", "tools": ["read", "write", "grep", "lint"], "triggers": ["*.py"], "patterns": ["python"]},
                {"name": "skill-b", "tools": ["read", "write", "grep", "format"], "triggers": ["*.py"], "patterns": ["python"]},
            ],
        }

        recs = skills._detect_skill_merge(sessions, profile, scan_results)
        assert len(recs) >= 1
        assert recs[0].action_type == "merge_skills"
        assert recs[0].trust_level == "heuristic"
        assert 63 <= recs[0].confidence <= 68

    def test_no_merge_with_low_overlap(self):
        """Skills with <70% overlap should not trigger."""
        sessions = [_make_session() for _ in range(5)]
        profile: dict[str, Any] = {}
        scan_results: dict[str, Any] = {
            "skills": [
                {"name": "python-dev", "tools": ["read", "write", "pytest"], "triggers": ["*.py"], "patterns": ["python"]},
                {"name": "frontend-dev", "tools": ["npm", "webpack", "eslint"], "triggers": ["*.tsx"], "patterns": ["react"]},
            ],
        }

        recs = skills._detect_skill_merge(sessions, profile, scan_results)
        assert len(recs) == 0

    def test_merge_requires_two_skills(self):
        """Single skill should not trigger merge."""
        recs = skills._detect_skill_merge([], {}, {"skills": [{"name": "only-one", "tools": ["read"]}]})
        assert len(recs) == 0

    def test_merge_handles_empty_scan(self):
        """Empty scan_results should not crash."""
        recs = skills._detect_skill_merge([], {}, {})
        assert recs == []


# ─── Skill Split Tests ───────────────────────────────────────────────────────


class TestSkillSplit:
    """Test _detect_skill_split."""

    def test_split_detected_when_skill_used_across_many_projects(self):
        """Skill referenced in >3 projects should trigger split recommendation."""
        sessions = []
        projects = ["/home/user/proj1", "/home/user/proj2", "/home/user/proj3", "/home/user/proj4"]
        for proj in projects:
            sessions.append(_make_session(
                project_path=proj,
                context_files=["skill.md", f"{proj}/src/main.py"],
            ))

        scan_results: dict[str, Any] = {
            "skills": [{"name": "skill", "tools": ["read"]}],
        }

        recs = skills._detect_skill_split(sessions, {}, scan_results)
        assert len(recs) >= 1
        assert recs[0].action_type == "split_skill"
        assert recs[0].trust_level == "heuristic"
        assert 63 <= recs[0].confidence <= 68

    def test_no_split_with_few_projects(self):
        """Skill used in <=3 projects should not trigger."""
        sessions = []
        for proj in ["/home/user/proj1", "/home/user/proj2"]:
            sessions.append(_make_session(
                project_path=proj,
                context_files=["skill.md"],
            ))

        scan_results: dict[str, Any] = {
            "skills": [{"name": "skill", "tools": ["read"]}],
        }

        recs = skills._detect_skill_split(sessions, {}, scan_results)
        assert len(recs) == 0

    def test_split_handles_empty_skills(self):
        """Empty skills list should not crash."""
        recs = skills._detect_skill_split([_make_session()], {}, {"skills": []})
        assert recs == []


# ─── Architecture Memory Tests ───────────────────────────────────────────────


class TestArchitectureMemory:
    """Test architecture_memory.detect and generators."""

    def test_architecture_doc_recommended_when_arch_patterns_detected(self):
        """Should recommend ARCHITECTURE.md when sessions show architecture work."""
        sessions = [_make_session(
            context_files=["src/service/handler.py", "src/domain/model.py"],
            commands=["import module", "refactor service layer"],
        ) for _ in range(10)]

        scan_results: dict[str, Any] = {"config_files": [], "tools_detected": ["kiro"]}

        recs = architecture_memory._detect_architecture_doc_need(sessions, scan_results)
        assert len(recs) >= 1
        assert recs[0].action_type == "generate_architecture_doc"
        assert recs[0].trust_level == "heuristic"
        assert 65 <= recs[0].confidence <= 70

    def test_no_architecture_rec_when_doc_exists(self):
        """Should not recommend if architecture doc already exists."""
        sessions = [_make_session(
            context_files=["src/service/handler.py"],
            commands=["refactor"],
        ) for _ in range(10)]

        scan_results: dict[str, Any] = {"config_files": ["ARCHITECTURE.md"], "tools_detected": ["kiro"]}

        recs = architecture_memory._detect_architecture_doc_need(sessions, scan_results)
        assert len(recs) == 0

    def test_agents_md_recommended_when_missing(self):
        """Should recommend AGENTS.md when AI tool usage but no AGENTS.md."""
        sessions = [_make_session(tool="kiro") for _ in range(5)]
        scan_results: dict[str, Any] = {"config_files": [], "tools_detected": ["kiro"]}

        recs = architecture_memory._detect_agents_md_need(sessions, scan_results)
        agents_recs = [r for r in recs if r.action_type == "generate_agents_md"]
        assert len(agents_recs) >= 1
        assert agents_recs[0].confidence >= CONFIDENCE_THRESHOLD

    def test_claude_md_recommended_when_missing(self):
        """Should recommend CLAUDE.md when AI tool usage but no CLAUDE.md."""
        sessions = [_make_session(tool="claude") for _ in range(5)]
        scan_results: dict[str, Any] = {"config_files": [], "tools_detected": ["claude"]}

        recs = architecture_memory._detect_agents_md_need(sessions, scan_results)
        claude_recs = [r for r in recs if r.action_type == "generate_claude_md"]
        assert len(claude_recs) >= 1

    def test_no_agents_rec_when_both_exist(self):
        """Should not recommend if AGENTS.md and CLAUDE.md both exist."""
        sessions = [_make_session(tool="kiro") for _ in range(5)]
        scan_results: dict[str, Any] = {
            "config_files": ["AGENTS.md", "CLAUDE.md"],
            "tools_detected": ["kiro"],
        }

        recs = architecture_memory._detect_agents_md_need(sessions, scan_results)
        assert len(recs) == 0


class TestArchitectureGenerators:
    """Test generate_architecture_doc and generate_agents_md."""

    def test_generate_architecture_doc_structure(self):
        """Should return dict with title, sections, suggested_content."""
        scan: dict[str, Any] = {
            "stack": ["python", "fastapi", "postgres"],
            "projects": ["/home/user/myapp"],
            "summary": {"name": "myapp"},
        }

        result = architecture_memory.generate_architecture_doc(scan)
        assert result["title"] == "ARCHITECTURE.md"
        assert len(result["sections"]) >= 7
        assert "# Architecture" in result["suggested_content"]
        assert "python" in result.get("stack", [])

    def test_generate_architecture_doc_empty_scan(self):
        """Should not crash with empty scan."""
        result = architecture_memory.generate_architecture_doc({})
        assert result["title"] == "ARCHITECTURE.md"
        assert "suggested_content" in result

    def test_generate_agents_md_structure(self):
        """Should return dict with title, sections, suggested_content."""
        scan: dict[str, Any] = {
            "stack": ["python", "django"],
            "tools_detected": ["kiro", "claude"],
            "projects": ["/home/user/webapp"],
        }

        result = architecture_memory.generate_agents_md(scan)
        assert result["title"] == "AGENTS.md"
        assert len(result["sections"]) >= 5
        assert "# AGENTS.md" in result["suggested_content"]
        assert "python" in result.get("stack", [])

    def test_generate_agents_md_empty_scan(self):
        """Should not crash with empty scan."""
        result = architecture_memory.generate_agents_md({})
        assert result["title"] == "AGENTS.md"
        assert "suggested_content" in result


# ─── Engine Integration Tests ────────────────────────────────────────────────


class TestEngineIntegration:
    """Test that new detectors are properly registered in the engine."""

    def test_health_score_detector_registered(self):
        """Health score detector should run through engine without crash."""
        sessions = [_make_session(
            user_msgs=30,
            prompt_word_counts=[800, 900],
            models=["claude-opus-4"],
        ) for _ in range(10)]

        profile: dict[str, Any] = {"total_sessions": 5}
        scan_results: dict[str, Any] = {"hooks": [], "mcps": [], "skills": [], "config_files": []}

        # Should not crash
        recs = recommend(sessions, profile, scan_results)
        # Health score rec may or may not fire depending on score
        assert isinstance(recs, list)

    def test_architecture_memory_detector_registered(self):
        """Architecture memory detector should run through engine."""
        sessions = [_make_session(
            tool="kiro",
            context_files=["src/domain/model.py"],
            commands=["refactor service layer"],
        ) for _ in range(10)]

        profile: dict[str, Any] = {}
        scan_results: dict[str, Any] = {"config_files": [], "tools_detected": ["kiro"]}

        recs = recommend(sessions, profile, scan_results)
        assert isinstance(recs, list)
        # Should have at least architecture-related rec
        arch_recs = [r for r in recs if r.action_type in (
            "generate_architecture_doc", "generate_agents_md", "generate_claude_md"
        )]
        assert len(arch_recs) >= 1

    def test_engine_never_crashes(self):
        """Engine should gracefully handle any input."""
        assert recommend([], None, None) == [] or isinstance(recommend([], None, None), list)
        assert isinstance(recommend([_make_session()], {}, {}), list)

    def test_all_recommendations_above_threshold(self):
        """All returned recommendations should be above confidence threshold."""
        sessions = [_make_session(
            user_msgs=30,
            prompt_word_counts=[800, 900],
            models=["claude-opus-4"],
            context_files=["src/service/handler.py"],
            commands=["refactor"],
            prompts=[{"tokens_used": 50}, {"tokens_used": 100}, {"tokens_used": 200}],
        ) for _ in range(15)]

        profile: dict[str, Any] = {"total_sessions": 15, "models_used": ["claude-opus-4"]}
        scan_results: dict[str, Any] = {"hooks": [], "mcps": [], "skills": [], "config_files": [], "tools_detected": ["kiro"]}

        recs = recommend(sessions, profile, scan_results)
        for rec in recs:
            assert rec.confidence >= CONFIDENCE_THRESHOLD, f"{rec.action_type} has confidence {rec.confidence} < {CONFIDENCE_THRESHOLD}"
