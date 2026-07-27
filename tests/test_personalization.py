"""Tests for cruise_ai.recommendations.personalization — Phase 4."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from cruise_ai.recommendations.personalization import (
    calculate_baseline,
    detect,
    detect_trends,
    mine_workflow_patterns,
)
from cruise_ai.recommendations.longitudinal import compare_periods, get_trend_data
from cruise_ai.recommendations.types import CONFIDENCE_THRESHOLD


# ─── Fixtures ────────────────────────────────────────────────────────────────


@dataclass
class FakeSession:
    """Minimal Session-like object for personalization tests."""

    tool: str = "kiro"
    session_id: str = "test"
    project_path: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    user_msgs: int = 5
    assistant_msgs: int = 5
    tool_calls_by_type: dict = field(default_factory=dict)
    models: list = field(default_factory=list)
    prompt_word_counts: list = field(default_factory=list)
    extras: dict = field(default_factory=dict)


def _make_sessions(
    count: int,
    avg_prompt_words: int = 30,
    user_msgs: int = 5,
    tool_calls: dict | None = None,
    commands: list | None = None,
) -> list[FakeSession]:
    """Generate uniform sessions for baseline tests."""
    sessions = []
    for i in range(count):
        started = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)
        sessions.append(FakeSession(
            session_id=f"s{i}",
            user_msgs=user_msgs,
            assistant_msgs=user_msgs,
            prompt_word_counts=[avg_prompt_words] * user_msgs,
            tool_calls_by_type=tool_calls or {"read": 2, "write": 1},
            started_at=started,
            ended_at=started + timedelta(minutes=30),
            extras={"commands": commands or []},
        ))
    return sessions


# ─── Test: Baseline Calculation ──────────────────────────────────────────────


class TestBaselineCalculation:
    """Tests for calculate_baseline()."""

    def test_empty_sessions(self):
        baseline = calculate_baseline([])
        assert baseline["avg_prompt_length"] == 0.0
        assert baseline["sample_size"] == 0

    def test_single_session(self):
        sessions = _make_sessions(1, avg_prompt_words=50)
        baseline = calculate_baseline(sessions)
        assert baseline["avg_prompt_length"] == 50.0
        assert baseline["stdev_prompt_length"] == 0.0
        assert baseline["sample_size"] == 1

    def test_varied_sessions(self):
        sessions = [
            FakeSession(prompt_word_counts=[20, 20, 20], user_msgs=3, assistant_msgs=3),
            FakeSession(prompt_word_counts=[40, 40, 40], user_msgs=3, assistant_msgs=3),
            FakeSession(prompt_word_counts=[60, 60, 60], user_msgs=3, assistant_msgs=3),
        ]
        baseline = calculate_baseline(sessions)
        # Mean of [20, 40, 60] = 40
        assert baseline["avg_prompt_length"] == 40.0
        assert baseline["stdev_prompt_length"] > 0
        assert baseline["sample_size"] == 3

    def test_tools_per_session(self):
        sessions = [
            FakeSession(tool_calls_by_type={"read": 3, "write": 2}),
            FakeSession(tool_calls_by_type={"read": 1}),
            FakeSession(tool_calls_by_type={}),
        ]
        baseline = calculate_baseline(sessions)
        # Tools: [5, 1, 0] -> mean ~2.0
        assert baseline["avg_tools_per_session"] == pytest.approx(2.0, abs=0.01)


# ─── Test: Relative Thresholds ───────────────────────────────────────────────


class TestRelativeThresholds:
    """Tests for threshold violation detection."""

    def test_no_trigger_normal_usage(self):
        """Normal sessions should NOT trigger threshold violations."""
        sessions = _make_sessions(10, avg_prompt_words=30)
        recs = detect(sessions, {}, {})
        # All sessions are uniform — no deviation — no personalization recs
        personalization_recs = [r for r in recs if r.category == "personalization"]
        assert len(personalization_recs) == 0

    def test_triggers_on_anomalous_prompts(self):
        """Sessions with outlier prompts should trigger."""
        # 8 normal sessions + 2 very long ones at the end
        sessions = _make_sessions(8, avg_prompt_words=30)
        for _ in range(2):
            sessions.append(FakeSession(
                prompt_word_counts=[200, 200, 200, 200, 200],
                user_msgs=5,
                assistant_msgs=5,
                tool_calls_by_type={"read": 2, "write": 1},
            ))
        recs = detect(sessions, {}, {})
        personalization_recs = [r for r in recs if r.category == "personalization"]
        prompt_recs = [r for r in personalization_recs if r.action_type == "optimize_prompts"]
        assert len(prompt_recs) >= 1

    def test_triggers_on_anomalous_tokens(self):
        """Sessions with much higher token usage should trigger."""
        sessions = _make_sessions(8, user_msgs=5)
        # Add 2 sessions with very high message counts (-> high token estimate)
        for _ in range(2):
            sessions.append(FakeSession(
                user_msgs=50,
                assistant_msgs=50,
                prompt_word_counts=[30] * 50,
                tool_calls_by_type={"read": 2},
            ))
        recs = detect(sessions, {}, {})
        token_recs = [r for r in recs if r.action_type == "reduce_token_usage"]
        assert len(token_recs) >= 1

    def test_insufficient_history_skips(self):
        """With fewer than 5 sessions, threshold checks are skipped."""
        sessions = _make_sessions(3, avg_prompt_words=30)
        # Add anomalous one
        sessions.append(FakeSession(
            prompt_word_counts=[500, 500, 500],
            user_msgs=3,
            assistant_msgs=3,
        ))
        recs = detect(sessions, {}, {})
        personalization_recs = [r for r in recs if r.category == "personalization"]
        # Should not trigger because sample_size < 5
        assert len(personalization_recs) == 0


# ─── Test: Workflow Pattern Mining ───────────────────────────────────────────


class TestWorkflowPatternMining:
    """Tests for mine_workflow_patterns()."""

    def test_empty_sessions(self):
        patterns = mine_workflow_patterns([])
        assert patterns == []

    def test_detects_repeated_sequence(self):
        """A command sequence repeated >5 times should be detected."""
        sessions = []
        for i in range(10):
            sessions.append(FakeSession(
                extras={"commands": ["read", "edit", "test", "commit"]},
                started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                ended_at=datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=20),
            ))
        patterns = mine_workflow_patterns(sessions)
        assert len(patterns) > 0
        # The sequence "read -> edit" should appear
        found = any("read" in p["sequence"] and "edit" in p["sequence"] for p in patterns)
        assert found

    def test_infrequent_pattern_excluded(self):
        """Patterns appearing <=5 times should not be returned."""
        sessions = []
        for i in range(3):
            sessions.append(FakeSession(
                extras={"commands": ["rare_a", "rare_b", "rare_c"]},
            ))
        patterns = mine_workflow_patterns(sessions)
        # Only 3 occurrences — should not qualify
        rare_patterns = [p for p in patterns if "rare_a" in p["sequence"]]
        assert len(rare_patterns) == 0

    def test_pattern_has_expected_keys(self):
        """Returned patterns should have required dict keys."""
        sessions = []
        for i in range(8):
            sessions.append(FakeSession(
                extras={"commands": ["search", "implement", "test"]},
                started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                ended_at=datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=15),
            ))
        patterns = mine_workflow_patterns(sessions)
        if patterns:
            p = patterns[0]
            assert "sequence" in p
            assert "frequency" in p
            assert "avg_duration" in p
            assert "friction_score" in p
            assert isinstance(p["sequence"], list)
            assert isinstance(p["frequency"], int)


# ─── Test: Trend Detection ───────────────────────────────────────────────────


class TestTrendDetection:
    """Tests for detect_trends()."""

    def test_insufficient_data(self):
        """Fewer than 3 weeks should return empty."""
        recs = detect_trends({"weekly_aggregates": [
            {"week": "2024-W01", "total_tokens": 100, "session_count": 5, "tools_used": {}},
        ]})
        assert recs == []

    def test_increasing_tokens_trend(self):
        """Consistently increasing token usage should trigger optimization rec."""
        weeks = [
            {"week": "2024-W01", "total_tokens": 1000, "session_count": 10, "tools_used": {}},
            {"week": "2024-W02", "total_tokens": 1500, "session_count": 10, "tools_used": {}},
            {"week": "2024-W03", "total_tokens": 2200, "session_count": 10, "tools_used": {}},
            {"week": "2024-W04", "total_tokens": 3000, "session_count": 10, "tools_used": {}},
        ]
        recs = detect_trends({"weekly_aggregates": weeks})
        token_recs = [r for r in recs if r.action_type == "optimize_token_growth"]
        assert len(token_recs) == 1
        assert token_recs[0].confidence >= CONFIDENCE_THRESHOLD

    def test_decreasing_sessions_trend(self):
        """Declining session counts should flag adoption friction."""
        weeks = [
            {"week": "2024-W01", "total_tokens": 1000, "session_count": 20, "tools_used": {}},
            {"week": "2024-W02", "total_tokens": 1000, "session_count": 15, "tools_used": {}},
            {"week": "2024-W03", "total_tokens": 1000, "session_count": 10, "tools_used": {}},
            {"week": "2024-W04", "total_tokens": 1000, "session_count": 5, "tools_used": {}},
        ]
        recs = detect_trends({"weekly_aggregates": weeks})
        adoption_recs = [r for r in recs if r.action_type == "address_adoption_friction"]
        assert len(adoption_recs) == 1

    def test_abandoned_tool_detection(self):
        """Tool used heavily then abandoned should trigger a rec."""
        weeks = [
            {"week": "2024-W01", "total_tokens": 1000, "session_count": 10, "tools_used": {"copilot": 10}},
            {"week": "2024-W02", "total_tokens": 1000, "session_count": 10, "tools_used": {"copilot": 8}},
            {"week": "2024-W03", "total_tokens": 1000, "session_count": 10, "tools_used": {}},
            {"week": "2024-W04", "total_tokens": 1000, "session_count": 10, "tools_used": {}},
        ]
        recs = detect_trends({"weekly_aggregates": weeks})
        abandoned_recs = [r for r in recs if r.action_type == "review_abandoned_tool"]
        assert len(abandoned_recs) == 1
        assert "copilot" in abandoned_recs[0].headline


# ─── Test: Engine Integration ────────────────────────────────────────────────


class TestEngineIntegration:
    """Test personalization works via the engine.recommend() interface."""

    def test_personalization_recs_through_engine(self):
        """Anomalous sessions should produce personalization recs through engine."""
        from cruise_ai.recommendations.engine import recommend

        # Build sessions with clear anomaly at the end
        sessions = _make_sessions(8, avg_prompt_words=30, user_msgs=5)
        for _ in range(2):
            sessions.append(FakeSession(
                prompt_word_counts=[300, 300, 300, 300, 300],
                user_msgs=5,
                assistant_msgs=5,
                tool_calls_by_type={"read": 2, "write": 1},
            ))

        recs = recommend(sessions)
        personalization_recs = [r for r in recs if r.category == "personalization"]
        # Should have at least one personalization rec
        assert len(personalization_recs) >= 1
        # All should meet confidence threshold
        for r in personalization_recs:
            assert r.confidence >= CONFIDENCE_THRESHOLD

    def test_engine_does_not_crash_with_empty_sessions(self):
        """Engine should handle empty input gracefully."""
        from cruise_ai.recommendations.engine import recommend

        recs = recommend([])
        assert isinstance(recs, list)


# ─── Test: Longitudinal Extensions ──────────────────────────────────────────


class TestLongitudinalExtensions:
    """Tests for get_trend_data() and compare_periods()."""

    def test_compare_periods_basic(self):
        """compare_periods returns proper before/after analysis."""
        period1 = {"avgPromptWords": 50, "totalActiveHours": 10}
        period2 = {"avgPromptWords": 40, "totalActiveHours": 15}
        result = compare_periods(period1, period2)
        assert "avgPromptWords" in result
        assert result["avgPromptWords"]["before"] == 50.0
        assert result["avgPromptWords"]["after"] == 40.0
        assert result["avgPromptWords"]["change"] == -10.0
        # Lower prompt words is improvement
        assert result["avgPromptWords"]["improved"] is True

    def test_compare_periods_handles_none(self):
        """compare_periods skips keys with None values."""
        period1 = {"avgPromptWords": 50, "missing": None}
        period2 = {"avgPromptWords": 60, "missing": 10}
        result = compare_periods(period1, period2)
        assert "missing" not in result
        assert "avgPromptWords" in result

    def test_get_trend_data_empty(self, tmp_path, monkeypatch):
        """get_trend_data returns empty aggregates with no data."""
        monkeypatch.setattr(
            "cruise_ai.recommendations.longitudinal._longitudinal_path",
            lambda: tmp_path / "longitudinal.json",
        )
        result = get_trend_data()
        assert result == {"weekly_aggregates": []}


# ─── Test: Confidence Range ──────────────────────────────────────────────────


class TestConfidenceRange:
    """Ensure personalization recs stay in the 65-80 confidence range."""

    def test_confidence_in_expected_range(self):
        """All personalization recs should have confidence 65-80."""
        sessions = _make_sessions(8, avg_prompt_words=30, user_msgs=5)
        # Add anomalous sessions
        for _ in range(2):
            sessions.append(FakeSession(
                prompt_word_counts=[250, 250, 250, 250, 250],
                user_msgs=5,
                assistant_msgs=5,
                tool_calls_by_type={"read": 20, "write": 15, "search": 10},
            ))
        recs = detect(sessions, {}, {})
        for r in recs:
            assert 65 <= r.confidence <= 80, f"confidence {r.confidence} out of range for {r.action_type}"
