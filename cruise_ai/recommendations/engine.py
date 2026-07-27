"""cruise_ai.recommendations.engine — orchestrates all recommendation rules.

Each category module exports a `detect(sessions, profile, scan_results) -> list[Recommendation]`
function. The engine collects them, deduplicates, confidence-gates, and returns
a sorted list.
"""

from __future__ import annotations

from typing import Any

from cruise_ai.recommendations.types import Recommendation, CONFIDENCE_THRESHOLD
from cruise_ai.recommendations import analytics as _analytics
from cruise_ai.recommendations import token_optimization as _token
from cruise_ai.recommendations import skills as _skills
from cruise_ai.recommendations import project_memory as _memory
from cruise_ai.recommendations import learning as _learning
from cruise_ai.recommendations import mcp_discovery as _mcp
from cruise_ai.recommendations import hooks as _hooks
from cruise_ai.recommendations import personalization as _personalization
from cruise_ai.recommendations import health_score as _health
from cruise_ai.recommendations import architecture_memory as _architecture
from cruise_ai.recommendations import eval_harness as _eval_harness
from cruise_ai.recommendations import reports as _reports
from cruise_ai.recommendations import team_guidelines as _team_guidelines
from cruise_ai.recommendations import learning_path as _learning_path


def recommend(
    sessions: list[Any],
    profile: dict[str, Any] | None = None,
    scan_results: dict[str, Any] | None = None,
) -> list[Recommendation]:
    """Run all recommendation detectors and return sorted results.

    Args:
        sessions: List of Session objects from adapters.
        profile: The profile.json dict (optional, for enriched signals).
        scan_results: The scan_results.json dict (optional).

    Returns:
        List of Recommendation objects sorted by priority then confidence.
    """
    profile = profile or {}
    scan_results = scan_results or {}

    all_recs: list[Recommendation] = []

    # Run each category detector
    for detector in [
        _analytics.detect,
        _token.detect,
        _skills.detect,
        _memory.detect,
        _learning.detect,
        _personalization.detect,
        _mcp.detect,
        _hooks.detect,
        _eval_harness.detect,
        _health.detect,
        _architecture.detect,
        _learning_path.detect,
        _reports.detect,
        _team_guidelines.detect,
    ]:
        try:
            recs = detector(sessions, profile, scan_results)
            all_recs.extend(recs)
        except Exception:
            continue  # never crash on a single detector failure

    # Apply feedback-based adjustments
    try:
        from cruise_ai.recommendations.feedback import (
            get_dismissed_action_types,
            confidence_adjustment,
        )
        dismissed = get_dismissed_action_types()
        for rec in all_recs:
            # Suppress dismissed recommendations
            if rec.action_type in dismissed:
                rec.confidence = 0  # will be filtered by gate
            else:
                # Adjust confidence based on historical feedback
                adj = confidence_adjustment(rec.action_type)
                rec.confidence = max(0, min(100, rec.confidence + adj))
    except Exception:
        pass  # feedback system failure should never block recommendations

    # Confidence gate
    all_recs = [r for r in all_recs if r.confidence >= CONFIDENCE_THRESHOLD]

    # Sort: high > medium > low, then by confidence desc
    priority_order = {"high": 0, "medium": 1, "low": 2}
    all_recs.sort(key=lambda r: (priority_order.get(r.priority, 1), -r.confidence))

    return all_recs
