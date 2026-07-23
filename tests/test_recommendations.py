"""Tests for cruise_ai.recommendations P0 features."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from cruise_ai.recommendations.engine import recommend
from cruise_ai.recommendations.types import Recommendation, CONFIDENCE_THRESHOLD
from cruise_ai.recommendations import analytics, token_optimization, skills, project_memory, learning


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
    extras: dict = field(default_factory=dict)


def make_session(
    tool="kiro",
    user_msgs=5,
    prompt_words=None,
    models=None,
    tools=None,
    project=None,
    started_at=None,
    session_id=None,
):
    import uuid
    return FakeSession(
        tool=tool,
        session_id=session_id or str(uuid.uuid4()),
        user_msgs=user_msgs,
        assistant_msgs=user_msgs,
        prompt_word_counts=prompt_words or [30, 25, 20, 35, 40],
        models=models or ["claude-sonnet-4-6"],
        tool_calls_by_type=tools or {"read": 3, "write": 2, "shell": 1},
        project_path=project or "/home/user/my-project",
        started_at=started_at or datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
    )


# ─── engine tests ─────────────────────────────────────────────────────────────

class TestRecommendationEngine:
    def test_empty_sessions_returns_empty(self):
        recs = recommend([], {}, {})
        assert recs == []

    def test_returns_list_of_recommendation_objects(self):
        sessions = [make_session(prompt_words=[400, 500, 600] * 10) for _ in range(30)]
        recs = recommend(sessions, {}, {})
        assert all(isinstance(r, Recommendation) for r in recs)

    def test_confidence_gate(self):
        sessions = [make_session() for _ in range(30)]
        recs = recommend(sessions, {}, {})
        assert all(r.confidence >= CONFIDENCE_THRESHOLD for r in recs)

    def test_sorted_by_priority(self):
        sessions = [make_session(
            prompt_words=[400, 500, 600, 700] * 5,
            models=["claude-opus-4-7"] * 1,
        ) for _ in range(30)]
        recs = recommend(sessions, {}, {})
        if len(recs) >= 2:
            priority_order = {"high": 0, "medium": 1, "low": 2}
            for i in range(len(recs) - 1):
                assert priority_order.get(recs[i].priority, 1) <= priority_order.get(recs[i + 1].priority, 1)

    def test_detector_exception_does_not_crash_engine(self, monkeypatch):
        """A broken detector should not crash the whole engine."""
        import cruise_ai.recommendations.analytics as _analytics
        monkeypatch.setattr(_analytics, "detect", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
        sessions = [make_session() for _ in range(10)]
        # Should not raise
        recs = recommend(sessions, {}, {})
        assert isinstance(recs, list)


# ─── analytics tests ──────────────────────────────────────────────────────────

class TestAnalytics:
    def test_dashboard_returns_required_keys(self):
        sessions = [make_session() for _ in range(10)]
        data = analytics.dashboard(sessions, {})
        assert "usage" in data
        assert "cost" in data
        assert "models" in data
        assert "projects" in data
        assert "tools" in data

    def test_usage_totals(self):
        sessions = [make_session(user_msgs=10, prompt_words=[50, 60, 70]) for _ in range(5)]
        data = analytics.dashboard(sessions, {})
        assert data["usage"]["total_sessions"] == 5
        assert data["usage"]["total_prompts"] == 50

    def test_cost_estimate_is_positive(self):
        sessions = [make_session(models=["claude-opus-4-7"]) for _ in range(20)]
        data = analytics.dashboard(sessions, {})
        assert data["cost"]["total_estimated_cost_usd"] >= 0

    def test_high_token_usage_generates_recommendation(self):
        # Create sessions with many words to exceed 500k token threshold
        sessions = [
            make_session(prompt_words=[500] * 100, user_msgs=100)
            for _ in range(20)
        ]
        recs = analytics.detect(sessions, {}, {})
        assert any(r.category == "analytics" for r in recs)

    def test_empty_sessions_returns_empty(self):
        recs = analytics.detect([], {}, {})
        assert recs == []

    def test_model_cost_matching(self):
        assert analytics._match_model_cost("claude-opus-4-7") == 0.030
        assert analytics._match_model_cost("claude-sonnet-4-6") == 0.006
        assert analytics._match_model_cost("claude-haiku-4-5") == 0.001


# ─── token_optimization tests ─────────────────────────────────────────────────

class TestTokenOptimization:
    def test_long_prompts_detected(self):
        # >20% of prompts should be long
        sessions = [
            make_session(prompt_words=[400, 500, 600, 30, 25])
            for _ in range(30)
        ]
        recs = token_optimization.detect(sessions, {}, {})
        long_recs = [r for r in recs if r.action_type == "compress_prompts"]
        assert len(long_recs) >= 1

    def test_short_prompts_no_long_detection(self):
        sessions = [make_session(prompt_words=[20, 30, 40, 50]) for _ in range(20)]
        recs = token_optimization.detect(sessions, {}, {})
        long_recs = [r for r in recs if r.action_type == "compress_prompts"]
        assert len(long_recs) == 0

    def test_duplicate_context_detected_for_clustered_first_prompts(self):
        # Sessions all starting with ~200-word first prompts (clustered)
        sessions = [
            make_session(prompt_words=[210 + (i % 10), 30, 25])
            for i in range(20)
        ]
        recs = token_optimization._detect_duplicate_context(sessions)
        assert any(r.action_type == "create_steering_doc" for r in recs)

    def test_single_model_detected(self):
        sessions = [
            make_session(models=["claude-opus-4-7"])
            for _ in range(25)
        ]
        recs = token_optimization._detect_model_opportunity(sessions, {})
        assert any(r.action_type == "model_routing" for r in recs)

    def test_too_few_sessions_skips_duplicate_detection(self):
        sessions = [make_session() for _ in range(3)]
        recs = token_optimization._detect_duplicate_context(sessions)
        assert recs == []

    def test_savings_estimate_present_on_long_prompt_rec(self):
        sessions = [
            make_session(prompt_words=[400, 500, 600, 700] * 3)
            for _ in range(30)
        ]
        recs = token_optimization._detect_long_prompts(sessions)
        if recs:
            assert "tokens" in recs[0].savings_estimate


# ─── skills tests ─────────────────────────────────────────────────────────────

class TestSkills:
    def test_frequent_tools_generate_skill_recommendation(self):
        sessions = [
            make_session(tools={"jira": 5, "confluence": 3, "gitlab": 2, "read": 10})
            for _ in range(20)
        ]
        recs = skills.detect(sessions, {}, {})
        skill_recs = [r for r in recs if r.action_type == "create_skill"]
        assert len(skill_recs) >= 1

    def test_no_subagent_usage_with_high_turns(self):
        sessions = [make_session(user_msgs=20) for _ in range(25)]
        profile = {"wrappedStats": {"subagentDispatches": 0}}
        recs = skills._detect_underutilized_tools(sessions)
        subagent_recs = [r for r in recs if r.action_type == "try_subagent_dispatch"]
        assert len(subagent_recs) >= 1

    def test_few_sessions_skips_detection(self):
        sessions = [make_session() for _ in range(5)]
        recs = skills.detect(sessions, {}, {})
        assert recs == []

    def test_skill_generator_returns_markdown(self):
        content = skills.generate_skill(
            name="Jira Workflow",
            description="Automate Jira ticket management",
            tools=["jira", "confluence"],
            pattern="Create ticket, link to PR, update documentation",
        )
        assert "# Jira Workflow" in content
        assert "jira" in content
        assert "confluence" in content
        assert "## Instructions" in content


# ─── project_memory tests ─────────────────────────────────────────────────────

class TestProjectMemory:
    def test_repeated_project_context_detected(self):
        # Many sessions in same project with large first prompts
        sessions = [
            make_session(
                project="/home/user/big-project",
                prompt_words=[150, 30, 25, 20],
            )
            for _ in range(15)
        ]
        recs = project_memory.detect(sessions, {}, {})
        memory_recs = [r for r in recs if r.action_type == "create_project_memory"]
        assert len(memory_recs) >= 1

    def test_small_session_count_skips_detection(self):
        sessions = [make_session() for _ in range(4)]
        recs = project_memory.detect(sessions, {}, {})
        assert recs == []

    def test_recommendation_includes_steering_doc_instructions(self):
        sessions = [
            make_session(project="/home/user/proj", prompt_words=[200, 30, 25])
            for _ in range(12)
        ]
        recs = project_memory.detect(sessions, {}, {})
        memory_recs = [r for r in recs if r.action_type == "create_project_memory"]
        if memory_recs:
            assert ".kiro/steering" in memory_recs[0].teach_text
            assert "CLAUDE.md" in memory_recs[0].teach_text

    def test_savings_estimate_includes_tokens(self):
        sessions = [
            make_session(project="/home/user/proj", prompt_words=[200, 50, 50])
            for _ in range(12)
        ]
        recs = project_memory.detect(sessions, {}, {})
        for r in recs:
            if r.action_type == "create_project_memory":
                assert "tokens" in r.savings_estimate


# ─── learning tests ───────────────────────────────────────────────────────────

class TestLearning:
    def test_plan_mode_recommendation_when_unused(self):
        profile = {
            "wrappedStats": {
                "planModePercent": 0.0,
                "subagentDispatches": 5,
                "avgPromptsPerSession": 8.0,
            }
        }
        sessions = [make_session() for _ in range(25)]
        recs = learning.detect(sessions, profile, {})
        plan_recs = [r for r in recs if r.action_type == "teach_plan_mode"]
        assert len(plan_recs) >= 1

    def test_subagent_recommendation_when_unused_with_high_turns(self):
        profile = {
            "wrappedStats": {
                "planModePercent": 10.0,
                "subagentDispatches": 0,
                "avgPromptsPerSession": 15.0,
            }
        }
        sessions = [make_session(user_msgs=15) for _ in range(35)]
        recs = learning.detect(sessions, profile, {})
        subagent_recs = [r for r in recs if r.action_type == "teach_subagents"]
        assert len(subagent_recs) >= 1

    def test_explain_recommendation_returns_string(self):
        rec = Recommendation(
            category="token_optimization",
            headline="Test headline",
            detail="Test detail",
            action_type="test_action",
            confidence=75,
            evidence="Test evidence",
            teach_text="Test teach text",
        )
        explanation = learning.explain_recommendation(rec)
        assert "Why This Recommendation?" in explanation
        assert "Test headline" in explanation
        assert "75%" in explanation

    def test_few_sessions_skips_learning_recs(self):
        sessions = [make_session() for _ in range(5)]
        recs = learning.detect(sessions, {}, {})
        assert recs == []

    def test_context_engineering_recommendation_for_verbose_prompts(self):
        profile = {
            "wrappedStats": {
                "avgPromptWords": 120,
                "planModePercent": 5.0,
                "subagentDispatches": 2,
                "avgPromptsPerSession": 8.0,
            }
        }
        sessions = [make_session() for _ in range(25)]
        recs = learning.detect(sessions, profile, {})
        context_recs = [r for r in recs if r.action_type == "teach_context_engineering"]
        assert len(context_recs) >= 1
