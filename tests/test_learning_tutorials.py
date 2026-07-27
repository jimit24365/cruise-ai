"""Tests for interactive tutorials and learning path features."""

from __future__ import annotations

import pytest

from cruise_ai.recommendations.learning import (
    TUTORIALS,
    get_tutorial,
    list_tutorials,
    _detect_tutorial_opportunity,
    detect as learning_detect,
)
from cruise_ai.recommendations.learning_path import (
    CONCEPTS,
    compute_learning_path,
    detect as learning_path_detect,
    _is_concept_mastered,
    _classify_level,
)
from cruise_ai.recommendations.engine import recommend
from cruise_ai.recommendations.types import Recommendation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_sessions(count: int = 10) -> list[dict]:
    """Create minimal session dicts for testing."""
    return [
        {
            "tool_name": "kiro",
            "tokens_used": 1000,
            "duration": 300,
            "model": "claude-sonnet",
            "prompts": ["fix the bug"],
            "context_files": ["src/main.py"],
            "commands": ["pytest"],
            "timestamp": f"2024-01-{i + 1:02d}T10:00:00Z",
        }
        for i in range(count)
    ]


def _make_profile(**overrides) -> dict:
    """Create a minimal profile dict."""
    base = {
        "tools_used": ["kiro"],
        "total_sessions": 10,
        "total_tokens": 10000,
        "projects": ["my-project"],
        "models_used": ["claude-sonnet"],
        "dimensions": {},
    }
    base.update(overrides)
    return base


def _make_scan_results(**overrides) -> dict:
    """Create minimal scan_results dict."""
    base = {
        "tools_detected": ["kiro"],
        "skills": [],
        "mcps": [],
        "hooks": [],
        "config_files": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tutorial System Tests
# ---------------------------------------------------------------------------


class TestListTutorials:
    """Tests for list_tutorials()."""

    def test_returns_all_topics(self):
        """list_tutorials returns all expected tutorial topic names."""
        topics = list_tutorials()
        expected = ["create_skill", "create_mcp", "create_hook", "optimize_prompts", "setup_memory"]
        assert sorted(topics) == sorted(expected)

    def test_returns_list_of_strings(self):
        """list_tutorials returns a list of strings."""
        topics = list_tutorials()
        assert isinstance(topics, list)
        assert all(isinstance(t, str) for t in topics)


class TestGetTutorial:
    """Tests for get_tutorial()."""

    def test_valid_topic_returns_structure(self):
        """get_tutorial returns dict with title and steps for valid topics."""
        for topic in list_tutorials():
            tutorial = get_tutorial(topic)
            assert "title" in tutorial, f"Missing title for {topic}"
            assert "steps" in tutorial, f"Missing steps for {topic}"
            assert isinstance(tutorial["steps"], list)
            assert len(tutorial["steps"]) >= 3, f"Too few steps for {topic}"

    def test_each_step_has_required_fields(self):
        """Each tutorial step has instruction, example, and validation."""
        for topic in list_tutorials():
            tutorial = get_tutorial(topic)
            for i, step in enumerate(tutorial["steps"]):
                assert "instruction" in step, f"{topic} step {i} missing instruction"
                assert "example" in step, f"{topic} step {i} missing example"
                assert "validation" in step, f"{topic} step {i} missing validation"
                assert len(step["instruction"]) > 10, f"{topic} step {i} instruction too short"
                assert len(step["example"]) > 5, f"{topic} step {i} example too short"

    def test_invalid_topic_returns_empty_dict(self):
        """get_tutorial returns empty dict for unknown topics."""
        assert get_tutorial("nonexistent_topic") == {}
        assert get_tutorial("") == {}

    def test_create_skill_tutorial_content(self):
        """create_skill tutorial has meaningful content."""
        tutorial = get_tutorial("create_skill")
        assert "Skill" in tutorial["title"] or "skill" in tutorial["title"]
        # First step should be about creating directory
        assert "kiro" in tutorial["steps"][0]["example"].lower() or "skill" in tutorial["steps"][0]["example"].lower()


class TestTutorialOpportunityDetection:
    """Tests for _detect_tutorial_opportunity()."""

    def test_no_skills_recommends_create_skill(self):
        """User with no skills gets create_skill tutorial recommendation."""
        sessions = _make_sessions(5)
        profile = _make_profile(total_sessions=5)
        scan = _make_scan_results(skills=[])

        recs = _detect_tutorial_opportunity(sessions, profile, scan)
        action_types = [r.action_type for r in recs]
        assert "start_tutorial_create_skill" in action_types

    def test_no_mcps_recommends_create_mcp(self):
        """User with no MCPs gets create_mcp tutorial recommendation."""
        sessions = _make_sessions(5)
        profile = _make_profile(total_sessions=5)
        scan = _make_scan_results(mcps=[])

        recs = _detect_tutorial_opportunity(sessions, profile, scan)
        action_types = [r.action_type for r in recs]
        assert "start_tutorial_create_mcp" in action_types

    def test_no_hooks_recommends_create_hook(self):
        """User with no hooks gets create_hook tutorial recommendation."""
        sessions = _make_sessions(5)
        profile = _make_profile(total_sessions=5)
        scan = _make_scan_results(hooks=[])

        recs = _detect_tutorial_opportunity(sessions, profile, scan)
        action_types = [r.action_type for r in recs]
        assert "start_tutorial_create_hook" in action_types

    def test_has_skills_no_skill_tutorial(self):
        """User with skills does NOT get create_skill tutorial recommendation."""
        sessions = _make_sessions(5)
        profile = _make_profile(total_sessions=5)
        scan = _make_scan_results(skills=["skill-a", "skill-b"])

        recs = _detect_tutorial_opportunity(sessions, profile, scan)
        action_types = [r.action_type for r in recs]
        assert "start_tutorial_create_skill" not in action_types

    def test_too_few_sessions_no_recommendations(self):
        """User with fewer than 3 sessions gets no tutorial recommendations."""
        sessions = _make_sessions(2)
        profile = _make_profile(total_sessions=2)
        scan = _make_scan_results()

        recs = _detect_tutorial_opportunity(sessions, profile, scan)
        assert recs == []

    def test_tutorial_recs_have_correct_trust_and_confidence(self):
        """Tutorial recommendations use trust_level='validated' and confidence=75."""
        sessions = _make_sessions(5)
        profile = _make_profile(total_sessions=5)
        scan = _make_scan_results()

        recs = _detect_tutorial_opportunity(sessions, profile, scan)
        for rec in recs:
            assert rec.trust_level == "validated"
            assert rec.confidence == 75

    def test_tutorial_recs_have_start_tutorial_action_type(self):
        """All tutorial recommendations have action_type starting with 'start_tutorial_'."""
        sessions = _make_sessions(5)
        profile = _make_profile(total_sessions=5)
        scan = _make_scan_results()

        recs = _detect_tutorial_opportunity(sessions, profile, scan)
        for rec in recs:
            assert rec.action_type.startswith("start_tutorial_")


# ---------------------------------------------------------------------------
# Learning Path Tests
# ---------------------------------------------------------------------------


class TestClassifyLevel:
    """Tests for _classify_level()."""

    def test_beginner_levels(self):
        assert _classify_level(0) == "beginner"
        assert _classify_level(1) == "beginner"
        assert _classify_level(2) == "beginner"

    def test_intermediate_levels(self):
        assert _classify_level(3) == "intermediate"
        assert _classify_level(4) == "intermediate"
        assert _classify_level(5) == "intermediate"

    def test_advanced_levels(self):
        assert _classify_level(6) == "advanced"
        assert _classify_level(7) == "advanced"
        assert _classify_level(8) == "advanced"

    def test_expert_level(self):
        assert _classify_level(9) == "expert"


class TestConceptMastery:
    """Tests for _is_concept_mastered()."""

    def test_basic_prompting_mastered_with_enough_sessions(self):
        """basic_prompting is mastered with 10+ sessions."""
        sessions = _make_sessions(10)
        profile = _make_profile(total_sessions=10)
        scan = _make_scan_results()
        assert _is_concept_mastered("basic_prompting", sessions, profile, scan) is True

    def test_basic_prompting_not_mastered_few_sessions(self):
        """basic_prompting not mastered with fewer than 10 sessions."""
        sessions = _make_sessions(5)
        profile = _make_profile(total_sessions=5)
        scan = _make_scan_results()
        assert _is_concept_mastered("basic_prompting", sessions, profile, scan) is False

    def test_tool_usage_mastered_with_many_tools(self):
        """tool_usage mastered with 3+ distinct tools."""
        sessions = _make_sessions(10)
        profile = _make_profile(tools_used=["kiro", "cursor", "claude-code", "copilot"])
        scan = _make_scan_results()
        assert _is_concept_mastered("tool_usage", sessions, profile, scan) is True

    def test_tool_usage_not_mastered_few_tools(self):
        """tool_usage not mastered with fewer than 3 tools."""
        sessions = _make_sessions(10)
        profile = _make_profile(tools_used=["kiro"])
        scan = _make_scan_results()
        assert _is_concept_mastered("tool_usage", sessions, profile, scan) is False

    def test_skills_mastered_with_enough_skills(self):
        """skills mastered with 3+ skills and enough sessions."""
        sessions = _make_sessions(15)
        profile = _make_profile(total_sessions=15)
        scan = _make_scan_results(skills=["a", "b", "c", "d"])
        assert _is_concept_mastered("skills", sessions, profile, scan) is True

    def test_mcps_mastered_with_enough_mcps(self):
        """mcps mastered with 2+ MCP servers."""
        sessions = _make_sessions(10)
        profile = _make_profile()
        scan = _make_scan_results(mcps=["filesystem", "github"])
        assert _is_concept_mastered("mcps", sessions, profile, scan) is True

    def test_hooks_mastered_with_enough_hooks(self):
        """hooks mastered with 2+ hooks configured."""
        sessions = _make_sessions(10)
        profile = _make_profile()
        scan = _make_scan_results(hooks=["post-edit", "pre-commit"])
        assert _is_concept_mastered("hooks", sessions, profile, scan) is True

    def test_memory_mastered_with_config_files(self):
        """memory mastered when project memory files exist."""
        sessions = _make_sessions(10)
        profile = _make_profile()
        scan = _make_scan_results(config_files=["CLAUDE.md", "package.json"])
        assert _is_concept_mastered("memory", sessions, profile, scan) is True

    def test_memory_not_mastered_without_memory_files(self):
        """memory not mastered without CLAUDE.md or steering docs."""
        sessions = _make_sessions(10)
        profile = _make_profile()
        scan = _make_scan_results(config_files=["package.json", "tsconfig.json"])
        assert _is_concept_mastered("memory", sessions, profile, scan) is False

    def test_multi_model_mastered_with_many_models(self):
        """multi_model mastered with 3+ different models."""
        sessions = _make_sessions(10)
        profile = _make_profile(models_used=["claude-sonnet", "gpt-4o", "gemini-pro"])
        scan = _make_scan_results()
        assert _is_concept_mastered("multi_model", sessions, profile, scan) is True

    def test_unknown_concept_returns_false(self):
        """Unknown concept name returns False (never crashes)."""
        sessions = _make_sessions(10)
        profile = _make_profile()
        scan = _make_scan_results()
        assert _is_concept_mastered("nonexistent_concept", sessions, profile, scan) is False


class TestComputeLearningPath:
    """Tests for compute_learning_path()."""

    def test_beginner_path(self):
        """New user with few sessions is beginner."""
        sessions = _make_sessions(3)
        profile = _make_profile(total_sessions=3, tools_used=["kiro"], models_used=["claude"])
        scan = _make_scan_results()

        path = compute_learning_path(sessions, profile, scan)
        assert path["current_level"] == "beginner"
        assert path["progress_pct"] < 30
        assert len(path["next_topics"]) > 0
        assert len(path["completed_topics"]) <= 2

    def test_intermediate_path(self):
        """User with moderate experience is intermediate."""
        sessions = _make_sessions(15)
        profile = _make_profile(
            total_sessions=15,
            tools_used=["kiro", "cursor", "claude-code"],
            models_used=["claude-sonnet", "gpt-4o", "gemini"],
        )
        scan = _make_scan_results(skills=["a", "b", "c", "d"])

        path = compute_learning_path(sessions, profile, scan)
        # Should have mastered: basic_prompting, tool_usage, skills, multi_model = 4
        assert path["current_level"] == "intermediate"
        assert 3 <= len(path["completed_topics"]) <= 5

    def test_advanced_path(self):
        """User with extensive setup is advanced."""
        sessions = _make_sessions(25)
        profile = _make_profile(
            total_sessions=25,
            tools_used=["kiro", "cursor", "claude-code", "pytest"],
            models_used=["claude-sonnet", "gpt-4o", "gemini"],
            dimensions={"test_coverage": 80},
        )
        scan = _make_scan_results(
            skills=["a", "b", "c", "d"],
            mcps=["filesystem", "github"],
            hooks=["post-edit", "pre-commit"],
            config_files=["CLAUDE.md", "package.json"],
        )

        path = compute_learning_path(sessions, profile, scan)
        assert path["current_level"] in ("advanced", "expert")
        assert len(path["completed_topics"]) >= 6

    def test_expert_path(self):
        """User with all concepts mastered is expert."""
        sessions = _make_sessions(30)
        profile = _make_profile(
            total_sessions=30,
            tools_used=["kiro", "cursor", "claude-code", "pytest", "vitest"],
            models_used=["claude-sonnet", "gpt-4o", "gemini"],
            dimensions={"test_coverage": 85},
        )
        scan = _make_scan_results(
            skills=["a", "b", "c", "d"],
            mcps=["filesystem", "github", "postgres"],
            hooks=["post-edit", "pre-commit", "on-save"],
            config_files=["CLAUDE.md", ".kiro/steering/context.md"],
        )

        path = compute_learning_path(sessions, profile, scan)
        assert path["current_level"] == "expert"
        assert path["progress_pct"] == 100
        assert path["next_topics"] == []

    def test_path_returns_correct_structure(self):
        """compute_learning_path always returns the expected keys."""
        sessions = _make_sessions(5)
        profile = _make_profile()
        scan = _make_scan_results()

        path = compute_learning_path(sessions, profile, scan)
        assert "current_level" in path
        assert "completed_topics" in path
        assert "next_topics" in path
        assert "progress_pct" in path
        assert isinstance(path["progress_pct"], int)
        assert 0 <= path["progress_pct"] <= 100

    def test_path_handles_empty_inputs(self):
        """compute_learning_path handles empty inputs gracefully."""
        path = compute_learning_path([], {}, {})
        assert path["current_level"] == "beginner"
        assert isinstance(path["completed_topics"], list)
        assert isinstance(path["next_topics"], list)


class TestLearningPathDetect:
    """Tests for learning_path.detect()."""

    def test_recommends_next_step_for_beginner(self):
        """Beginner gets a recommendation for their next learning step."""
        sessions = _make_sessions(5)
        profile = _make_profile(total_sessions=5, tools_used=["kiro"])
        scan = _make_scan_results()

        recs = learning_path_detect(sessions, profile, scan)
        assert len(recs) >= 1
        rec = recs[0]
        assert rec.action_type == "advance_learning_path"
        assert rec.category == "learning"
        assert rec.trust_level == "observed"
        assert rec.confidence == 72

    def test_no_recommendation_for_expert(self):
        """Expert user gets no learning path recommendations."""
        sessions = _make_sessions(30)
        profile = _make_profile(
            total_sessions=30,
            tools_used=["kiro", "cursor", "claude", "pytest", "vitest"],
            models_used=["claude-sonnet", "gpt-4o", "gemini"],
            dimensions={"test_coverage": 85},
        )
        scan = _make_scan_results(
            skills=["a", "b", "c", "d"],
            mcps=["filesystem", "github", "postgres"],
            hooks=["post-edit", "pre-commit", "on-save"],
            config_files=["CLAUDE.md", ".kiro/steering/context.md"],
        )

        recs = learning_path_detect(sessions, profile, scan)
        assert len(recs) == 0

    def test_recommendation_includes_level_info(self):
        """Learning path recommendation includes level and progress info."""
        sessions = _make_sessions(12)
        profile = _make_profile(
            total_sessions=12,
            tools_used=["kiro", "cursor", "claude-code"],
        )
        scan = _make_scan_results()

        recs = learning_path_detect(sessions, profile, scan)
        assert len(recs) >= 1
        rec = recs[0]
        assert "Learning Path:" in rec.headline
        assert "progress" in rec.detail.lower() or "level" in rec.detail.lower()


# ---------------------------------------------------------------------------
# Engine Integration Tests
# ---------------------------------------------------------------------------


class TestEngineIntegration:
    """Tests for learning features integrated with the recommendation engine."""

    def test_engine_includes_learning_path_recs(self):
        """Recommendation engine includes learning path recommendations."""
        sessions = _make_sessions(5)
        profile = _make_profile(total_sessions=5)
        scan = _make_scan_results()

        recs = recommend(sessions, profile, scan)
        action_types = [r.action_type for r in recs]
        assert "advance_learning_path" in action_types

    def test_engine_includes_tutorial_recs(self):
        """Recommendation engine includes tutorial recommendations."""
        sessions = _make_sessions(5)
        profile = _make_profile(total_sessions=5)
        scan = _make_scan_results()

        recs = recommend(sessions, profile, scan)
        tutorial_recs = [r for r in recs if r.action_type.startswith("start_tutorial_")]
        assert len(tutorial_recs) > 0

    def test_engine_never_crashes_with_learning_features(self):
        """Engine handles malformed inputs without crashing."""
        # All None-ish inputs
        recs = recommend([], None, None)
        assert isinstance(recs, list)

        # Malformed profile
        recs = recommend(_make_sessions(5), {"bad_key": object()}, {"skills": None})
        assert isinstance(recs, list)
