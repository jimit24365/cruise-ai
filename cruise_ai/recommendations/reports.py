"""cruise_ai.recommendations.reports — monthly report generation and recommendation.

Provides:
- generate_monthly_report: produce monthly usage/insights summary
- detect: recommend viewing monthly report when enough data exists
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from cruise_ai.recommendations.types import Recommendation

# Approximate cost per 1K tokens (blended)
_MODEL_COSTS_PER_1K: dict[str, float] = {
    "claude-opus": 0.030,
    "claude-sonnet": 0.006,
    "claude-haiku": 0.001,
    "gpt-4o": 0.010,
    "gpt-4": 0.040,
    "gpt-3.5": 0.001,
    "gemini-pro": 0.004,
    "gemini-flash": 0.001,
    "deepseek": 0.002,
}


def _match_model_cost(model_name: str) -> float:
    """Match a model name to its approximate cost tier."""
    name = model_name.lower()
    for prefix, cost in _MODEL_COSTS_PER_1K.items():
        if prefix.replace("-", "") in name.replace("-", ""):
            return cost
    return 0.006


def _get_session_timestamp(session: Any) -> datetime | None:
    """Extract timestamp from a session."""
    try:
        if isinstance(session, dict):
            ts = session.get("timestamp", "")
        else:
            ts = getattr(session, "timestamp", "")
        if isinstance(ts, datetime):
            return ts
        if isinstance(ts, str) and ts:
            # Try ISO format
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        pass
    return None


def generate_monthly_report(
    sessions: list[Any],
    profile: dict[str, Any],
    longitudinal_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a monthly usage and insights report.

    Args:
        sessions: All session data.
        profile: User profile dict.
        longitudinal_data: Historical trend data (optional).

    Returns:
        Dict with period, total_sessions, total_tokens, cost_estimate,
        top_recommendations, trends, health_score_change.
    """
    longitudinal_data = longitudinal_data or {}

    # Determine period
    now = datetime.now()
    period_start = now - timedelta(days=30)
    period = f"{period_start.strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}"

    # Filter sessions to period
    period_sessions = []
    for s in sessions:
        ts = _get_session_timestamp(s)
        if ts is None or ts >= period_start:
            period_sessions.append(s)

    total_sessions = len(period_sessions)

    # Compute token total
    total_tokens = 0
    model_tokens: dict[str, int] = {}
    for s in period_sessions:
        if isinstance(s, dict):
            tokens = s.get("tokens_used", 0)
            model = s.get("model", "unknown")
        else:
            tokens = getattr(s, "tokens_used", 0) or 0
            model = getattr(s, "model", "unknown") or "unknown"
        total_tokens += tokens
        model_tokens[model] = model_tokens.get(model, 0) + tokens

    # Estimate cost
    cost_estimate = 0.0
    for model, tokens in model_tokens.items():
        cost_per_1k = _match_model_cost(model)
        cost_estimate += (tokens / 1000) * cost_per_1k

    # Trends from longitudinal data
    trends: list[str] = []
    prev_tokens = longitudinal_data.get("prev_month_tokens", 0)
    if prev_tokens and total_tokens:
        change_pct = ((total_tokens - prev_tokens) / prev_tokens) * 100
        if change_pct > 10:
            trends.append(f"Token usage up {change_pct:.0f}% vs last month")
        elif change_pct < -10:
            trends.append(f"Token usage down {abs(change_pct):.0f}% vs last month")
        else:
            trends.append("Token usage stable vs last month")

    prev_sessions = longitudinal_data.get("prev_month_sessions", 0)
    if prev_sessions and total_sessions:
        sess_change = ((total_sessions - prev_sessions) / prev_sessions) * 100
        if sess_change > 10:
            trends.append(f"Sessions up {sess_change:.0f}% vs last month")
        elif sess_change < -10:
            trends.append(f"Sessions down {abs(sess_change):.0f}% vs last month")

    # Health score change
    current_health = longitudinal_data.get("current_health_score", 0)
    prev_health = longitudinal_data.get("prev_health_score", 0)
    health_score_change = current_health - prev_health

    # Top recommendations (placeholder — in practice fed by engine)
    top_recommendations = longitudinal_data.get("top_recommendations", [])

    return {
        "period": period,
        "total_sessions": total_sessions,
        "total_tokens": total_tokens,
        "cost_estimate": round(cost_estimate, 2),
        "top_recommendations": top_recommendations[:5],
        "trends": trends,
        "health_score_change": health_score_change,
    }


def detect(
    sessions: list[Any], profile: dict[str, Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Recommend viewing monthly report when sufficient data is available.

    Triggers when >30 days of session data exists or aiUsageSpanDays > 30.
    """
    recs: list[Recommendation] = []
    try:
        # Session-based detection
        if sessions and len(sessions) >= 5:
            # Check if we have >30 days of data
            timestamps: list[datetime] = []
            for s in sessions:
                ts = _get_session_timestamp(s)
                if ts:
                    timestamps.append(ts)

            if not timestamps:
                # If no parseable timestamps but many sessions, still recommend
                if len(sessions) >= 30:
                    recs.append(Recommendation(
                        category="analytics",
                        headline="Monthly report available — review your AI usage trends",
                        detail=(
                            f"You have {len(sessions)} sessions of data. "
                            f"A monthly report summarizes token usage, cost estimates, "
                            f"and top optimization opportunities."
                        ),
                        action_type="view_monthly_report",
                        trust_level="validated",
                        confidence=80,
                        evidence=f"{len(sessions)} sessions available for analysis",
                        priority="low",
                        teach_text=(
                            "Monthly reports help you track AI usage trends over time. "
                            "They highlight cost changes, usage patterns, and which "
                            "optimizations had the most impact."
                        ),
                        auto_action="Generate and display monthly usage report",
                    ))
                return recs

            date_range = max(timestamps) - min(timestamps)
            if date_range.days >= 30:
                recs.append(Recommendation(
                    category="analytics",
                    headline="Monthly report available — review your AI usage trends",
                    detail=(
                        f"You have {date_range.days} days of session data ({len(sessions)} sessions). "
                        f"A monthly report summarizes token usage, cost estimates, trends, "
                        f"and top optimization opportunities."
                    ),
                    action_type="view_monthly_report",
                    trust_level="validated",
                    confidence=80,
                    evidence=f"{len(sessions)} sessions spanning {date_range.days} days",
                    priority="low",
                    teach_text=(
                        "Monthly reports help you track AI usage trends over time. "
                        "They highlight cost changes, usage patterns, and which "
                        "optimizations had the most impact."
                    ),
                    auto_action="Generate and display monthly usage report",
                ))

        # Normalized-signal detection
        norm = scan_results.get("normalized", {}) if scan_results else {}
        if norm and not sessions:
            ai_usage_span_days = norm.get("aiUsageSpanDays", 0)
            total_sessions = norm.get("totalSessions", 0)
            # aiUsageSpanDays > 30 -> monthly report available
            if ai_usage_span_days > 30:
                recs.append(Recommendation(
                    category="analytics",
                    headline="Monthly report available — review your AI usage trends",
                    detail=(
                        f"You have {ai_usage_span_days} days of AI usage data ({total_sessions} sessions). "
                        f"A monthly report summarizes token usage, cost estimates, trends, "
                        f"and top optimization opportunities."
                    ),
                    action_type="view_monthly_report",
                    trust_level="heuristic",
                    confidence=75,
                    evidence=f"{total_sessions} sessions over {ai_usage_span_days} days (normalized)",
                    priority="low",
                    teach_text=(
                        "Monthly reports help you track AI usage trends over time. "
                        "They highlight cost changes, usage patterns, and which "
                        "optimizations had the most impact."
                    ),
                    auto_action="Generate and display monthly usage report",
                ))
    except Exception:
        pass

    return recs
