"""Tests for cruise_ai.recommendations.eval_metrics and calibration modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from cruise_ai.recommendations.eval_metrics import (
    compute_precision,
    compute_recall_proxy,
    per_detector_metrics,
)
from cruise_ai.recommendations.calibration import (
    calibrate_thresholds,
    apply_calibration,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@dataclass
class FakeSession:
    """Minimal Session-like object for tests."""

    tool: str = "kiro"
    session_id: str = "test-session"
    user_msgs: int = 5
    assistant_msgs: int = 5
    prompt_word_counts: list = field(default_factory=list)
    tool_calls_by_type: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)
    models: list = field(default_factory=list)


@dataclass
class FakeRecommendation:
    """Minimal Recommendation-like object for tests."""

    category: str = "token_optimization"
    action_type: str = "compress_prompts"
    confidence: int = 75


def _make_feedback(action_type: str, response: str) -> dict[str, Any]:
    """Create a single feedback entry."""
    return {
        "action_type": action_type,
        "category": "test",
        "response": response,
        "timestamp": 1700000000.0,
    }


# ─── Test compute_precision ──────────────────────────────────────────────────


class TestComputePrecision:
    def test_empty_feedback(self):
        assert compute_precision([]) == 0.0

    def test_all_positive(self):
        data = [
            _make_feedback("a", "acted"),
            _make_feedback("b", "useful"),
            _make_feedback("c", "acted"),
        ]
        assert compute_precision(data) == 1.0

    def test_all_negative(self):
        data = [
            _make_feedback("a", "dismissed"),
            _make_feedback("b", "not_useful"),
        ]
        assert compute_precision(data) == 0.0

    def test_mixed_feedback(self):
        data = [
            _make_feedback("a", "acted"),
            _make_feedback("b", "useful"),
            _make_feedback("c", "dismissed"),
            _make_feedback("d", "not_useful"),
        ]
        # 2 positive out of 4
        assert compute_precision(data) == 0.5

    def test_partial_positive(self):
        data = [
            _make_feedback("a", "acted"),
            _make_feedback("b", "dismissed"),
            _make_feedback("c", "dismissed"),
        ]
        # 1/3
        assert abs(compute_precision(data) - 1 / 3) < 0.001


# ─── Test compute_recall_proxy ───────────────────────────────────────────────


class TestComputeRecallProxy:
    def test_no_sessions(self):
        assert compute_recall_proxy([], []) == 1.0

    def test_no_opportunities(self):
        # Sessions with no patterns that should trigger recs
        sessions = [FakeSession(prompt_word_counts=[30, 40, 50])]
        assert compute_recall_proxy(sessions, []) == 1.0

    def test_detected_long_prompts(self):
        sessions = [FakeSession(prompt_word_counts=[600, 700])]
        recs = [FakeRecommendation(category="token_optimization")]
        result = compute_recall_proxy(sessions, recs)
        assert result == 1.0  # opportunity detected

    def test_missed_long_prompts(self):
        sessions = [FakeSession(prompt_word_counts=[600, 700])]
        recs = [FakeRecommendation(category="skills")]  # wrong category
        result = compute_recall_proxy(sessions, recs)
        assert result == 0.0  # 1 opportunity, 0 detected

    def test_partial_detection(self):
        sessions = [
            FakeSession(prompt_word_counts=[600]),  # opportunity: token_optimization
            FakeSession(tool_calls_by_type={"edit": 15, "read": 10}),  # opportunity: skills
        ]
        # Only token_optimization rec, not skills
        recs = [FakeRecommendation(category="token_optimization")]
        result = compute_recall_proxy(sessions, recs)
        assert result == 0.5  # 1 of 2 detected

    def test_many_tool_calls_detected(self):
        sessions = [FakeSession(tool_calls_by_type={"edit": 15, "read": 10})]
        recs = [FakeRecommendation(category="skills")]
        result = compute_recall_proxy(sessions, recs)
        assert result == 1.0


# ─── Test per_detector_metrics ───────────────────────────────────────────────


class TestPerDetectorMetrics:
    def test_empty_data(self):
        assert per_detector_metrics([]) == {}

    def test_single_detector(self):
        data = [
            _make_feedback("compress_prompts", "acted"),
            _make_feedback("compress_prompts", "useful"),
            _make_feedback("compress_prompts", "dismissed"),
        ]
        result = per_detector_metrics(data)
        assert "compress_prompts" in result
        m = result["compress_prompts"]
        assert m["total_feedback"] == 3
        assert m["useful_count"] == 2
        assert abs(m["precision"] - 2 / 3) < 0.001

    def test_multiple_detectors(self):
        data = [
            _make_feedback("compress_prompts", "acted"),
            _make_feedback("compress_prompts", "not_useful"),
            _make_feedback("adopt_tool", "useful"),
            _make_feedback("adopt_tool", "useful"),
            _make_feedback("adopt_tool", "dismissed"),
        ]
        result = per_detector_metrics(data)
        assert len(result) == 2
        assert result["compress_prompts"]["precision"] == 0.5
        assert abs(result["adopt_tool"]["precision"] - 2 / 3) < 0.001

    def test_all_unknown_action_types(self):
        data = [{"response": "acted", "action_type": "unknown"}]
        result = per_detector_metrics(data)
        assert "unknown" in result
        assert result["unknown"]["useful_count"] == 1


# ─── Test calibrate_thresholds ───────────────────────────────────────────────


class TestCalibrateThresholds:
    def test_empty_feedback(self):
        assert calibrate_thresholds([], {}) == {}

    def test_insufficient_data(self):
        # Only 5 entries — below 10 threshold
        data = [_make_feedback("a", "acted") for _ in range(5)]
        result = calibrate_thresholds(data, {})
        assert result == {}  # gracefully returns empty

    def test_high_useful_rate_lowers_threshold(self):
        # 11 entries, 10 useful (91% useful rate > 80%)
        data = [_make_feedback("compress_prompts", "useful") for _ in range(10)]
        data.append(_make_feedback("compress_prompts", "dismissed"))
        result = calibrate_thresholds(data, {"snapshots": [], "outcomes": []})
        assert "compress_prompts" in result
        r = result["compress_prompts"]
        assert r["suggested_threshold"] < r["current_threshold"]
        assert "lower threshold" in r["evidence"].lower() or "valuable" in r["evidence"].lower()

    def test_high_not_useful_rate_raises_threshold(self):
        # 12 entries, 7 not_useful (58% > 50%)
        data = [_make_feedback("noisy_detector", "not_useful") for _ in range(7)]
        data.extend([_make_feedback("noisy_detector", "acted") for _ in range(5)])
        result = calibrate_thresholds(data, {"snapshots": [], "outcomes": []})
        assert "noisy_detector" in result
        r = result["noisy_detector"]
        assert r["suggested_threshold"] > r["current_threshold"]
        assert "raise threshold" in r["evidence"].lower() or "noisy" in r["evidence"].lower()

    def test_stable_threshold_unchanged(self):
        # 12 entries: 6 useful, 3 not_useful, 3 dismissed — moderate rates
        data = [_make_feedback("stable_det", "useful") for _ in range(6)]
        data.extend([_make_feedback("stable_det", "not_useful") for _ in range(3)])
        data.extend([_make_feedback("stable_det", "dismissed") for _ in range(3)])
        result = calibrate_thresholds(data, {"snapshots": [], "outcomes": []})
        assert "stable_det" in result
        r = result["stable_det"]
        assert r["suggested_threshold"] == r["current_threshold"]

    def test_longitudinal_improvement_lowers_further(self):
        # High useful rate + strong longitudinal improvement
        data = [_make_feedback("improving", "useful") for _ in range(10)]
        data.append(_make_feedback("improving", "dismissed"))
        longitudinal = {
            "snapshots": [],
            "outcomes": [
                {"action_type": "improving", "improved": True},
                {"action_type": "improving", "improved": True},
                {"action_type": "improving", "improved": True},
            ],
        }
        result = calibrate_thresholds(data, longitudinal)
        r = result["improving"]
        # Should be lower than default - 10 (extra -5 from longitudinal)
        assert r["suggested_threshold"] <= r["current_threshold"] - 10
        assert "longitudinal" in r["evidence"].lower()


# ─── Test apply_calibration ──────────────────────────────────────────────────


class TestApplyCalibration:
    def test_empty_results_no_crash(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "cruise_ai.recommendations.calibration._config_path",
            lambda: tmp_path / "calibration.json",
        )
        apply_calibration({})
        assert not (tmp_path / "calibration.json").exists()

    def test_persists_thresholds(self, tmp_path, monkeypatch):
        import json

        config_file = tmp_path / "calibration.json"
        monkeypatch.setattr(
            "cruise_ai.recommendations.calibration._config_path",
            lambda: config_file,
        )

        results = {
            "compress_prompts": {
                "current_threshold": 60,
                "suggested_threshold": 50,
                "evidence": "High useful rate",
            }
        }
        apply_calibration(results)

        assert config_file.exists()
        saved = json.loads(config_file.read_text())
        assert saved["compress_prompts"]["threshold"] == 50
        assert "High useful rate" in saved["compress_prompts"]["evidence"]

    def test_updates_existing_config(self, tmp_path, monkeypatch):
        import json

        config_file = tmp_path / "calibration.json"
        config_file.write_text(json.dumps({"old_key": {"threshold": 70}}))
        monkeypatch.setattr(
            "cruise_ai.recommendations.calibration._config_path",
            lambda: config_file,
        )

        results = {
            "new_key": {
                "current_threshold": 60,
                "suggested_threshold": 45,
                "evidence": "test",
            }
        }
        apply_calibration(results)

        saved = json.loads(config_file.read_text())
        assert saved["old_key"]["threshold"] == 70  # preserved
        assert saved["new_key"]["threshold"] == 45  # added
