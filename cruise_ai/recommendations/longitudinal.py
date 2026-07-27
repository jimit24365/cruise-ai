"""cruise_ai.recommendations.longitudinal — track outcomes over time.

Records the state of key metrics when recommendations are generated,
then compares on subsequent assessments to measure if acting on
a recommendation actually improved things.

Storage: ~/.cruise-ai/data/longitudinal.json
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _longitudinal_path() -> Path:
    """Return path to longitudinal tracking file."""
    from cruise_ai.paths import data_dir
    return data_dir() / "longitudinal.json"


def _load_data() -> dict[str, Any]:
    """Load longitudinal tracking data."""
    path = _longitudinal_path()
    if not path.exists():
        return {"snapshots": [], "outcomes": []}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {"snapshots": [], "outcomes": []}
    except (json.JSONDecodeError, OSError):
        return {"snapshots": [], "outcomes": []}


def _save_data(data: dict[str, Any]) -> None:
    """Persist longitudinal tracking data."""
    path = _longitudinal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def record_snapshot(profile: dict[str, Any], recommendations: list[Any]) -> dict[str, Any]:
    """Record a snapshot of current metrics alongside active recommendations.

    Called after each assessment + recommendation run.

    Args:
        profile: The current profile.json dict.
        recommendations: List of Recommendation objects generated.

    Returns:
        The recorded snapshot.
    """
    wrapped = profile.get("wrappedStats", {})

    snapshot = {
        "timestamp": time.time(),
        "date": time.strftime("%Y-%m-%d"),
        "metrics": {
            "avgPromptWords": wrapped.get("avgPromptWords"),
            "avgPromptsPerSession": wrapped.get("avgPromptsPerSession"),
            "planModePercent": wrapped.get("planModePercent"),
            "subagentDispatches": wrapped.get("subagentDispatches"),
            "deepSessionCount": wrapped.get("deepSessionCount"),
            "totalActiveHours": wrapped.get("totalActiveHours"),
        },
        "recommendations_generated": [
            {
                "action_type": getattr(r, "action_type", ""),
                "category": getattr(r, "category", ""),
                "confidence": getattr(r, "confidence", 0),
            }
            for r in recommendations
        ],
        "recommendation_count": len(recommendations),
    }

    data = _load_data()
    data["snapshots"].append(snapshot)

    # Keep only last 50 snapshots
    if len(data["snapshots"]) > 50:
        data["snapshots"] = data["snapshots"][-50:]

    _save_data(data)
    return snapshot


def record_outcome(action_type: str, before_value: Any, after_value: Any, metric_name: str) -> None:
    """Record a measured outcome after acting on a recommendation.

    Args:
        action_type: Which recommendation was acted on.
        before_value: Metric value before acting.
        after_value: Metric value after acting.
        metric_name: Which metric changed (e.g. "avgPromptWords").
    """
    outcome = {
        "timestamp": time.time(),
        "date": time.strftime("%Y-%m-%d"),
        "action_type": action_type,
        "metric_name": metric_name,
        "before": before_value,
        "after": after_value,
        "improved": _is_improvement(metric_name, before_value, after_value),
    }

    data = _load_data()
    data["outcomes"].append(outcome)
    _save_data(data)


def _is_improvement(metric_name: str, before: Any, after: Any) -> bool | None:
    """Determine if a metric change is an improvement.

    Some metrics improve by decreasing (avgPromptWords, cost),
    others by increasing (subagentDispatches, planModePercent).
    """
    if before is None or after is None:
        return None

    # Metrics where LOWER is better
    lower_is_better = {"avgPromptWords", "cost", "correction_loops"}
    # Metrics where HIGHER is better
    higher_is_better = {"subagentDispatches", "planModePercent", "deepSessionCount", "firstShotAcceptRate"}

    try:
        before_f = float(before)
        after_f = float(after)
    except (TypeError, ValueError):
        return None

    if metric_name in lower_is_better:
        return after_f < before_f
    elif metric_name in higher_is_better:
        return after_f > before_f
    return None


def compare_snapshots() -> dict[str, Any]:
    """Compare the most recent snapshot to the earliest.

    Returns trends for each tracked metric.
    """
    data = _load_data()
    snapshots = data.get("snapshots", [])

    if len(snapshots) < 2:
        return {"status": "insufficient_data", "snapshots_count": len(snapshots)}

    first = snapshots[0]
    latest = snapshots[-1]
    first_metrics = first.get("metrics", {})
    latest_metrics = latest.get("metrics", {})

    trends: dict[str, dict] = {}
    for key in first_metrics:
        before = first_metrics.get(key)
        after = latest_metrics.get(key)
        if before is not None and after is not None:
            try:
                change = float(after) - float(before)
                pct_change = (change / float(before) * 100) if float(before) != 0 else 0
                trends[key] = {
                    "before": before,
                    "after": after,
                    "change": round(change, 2),
                    "pct_change": round(pct_change, 1),
                    "improved": _is_improvement(key, before, after),
                }
            except (TypeError, ValueError):
                pass

    return {
        "status": "ok",
        "snapshots_count": len(snapshots),
        "first_date": first.get("date"),
        "latest_date": latest.get("date"),
        "trends": trends,
        "outcomes": data.get("outcomes", []),
    }


def get_trend_data() -> dict[str, Any]:
    """Return weekly aggregates from longitudinal snapshots for trend detection.

    Groups snapshots by ISO week and computes totals for each week.

    Returns:
        Dict with 'weekly_aggregates': list of dicts with week, total_tokens,
        session_count, and tools_used.
    """
    data = _load_data()
    snapshots = data.get("snapshots", [])

    if not snapshots:
        return {"weekly_aggregates": []}

    # Group snapshots by ISO week
    weeks: dict[str, dict[str, Any]] = {}
    for snap in snapshots:
        date_str = snap.get("date", "")
        if not date_str:
            continue
        try:
            from datetime import date as _date
            d = _date.fromisoformat(date_str)
            week_key = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
        except (ValueError, TypeError):
            continue

        if week_key not in weeks:
            weeks[week_key] = {
                "week": week_key,
                "total_tokens": 0,
                "session_count": 0,
                "tools_used": {},
            }

        metrics = snap.get("metrics", {})
        # Approximate tokens from active hours (rough proxy)
        active_hours = metrics.get("totalActiveHours") or 0
        weeks[week_key]["total_tokens"] += int(active_hours * 5000)
        weeks[week_key]["session_count"] += snap.get("recommendation_count", 1)

    # Sort by week key
    sorted_weeks = sorted(weeks.values(), key=lambda w: w["week"])
    return {"weekly_aggregates": sorted_weeks}


def compare_periods(
    period1_data: dict[str, Any], period2_data: dict[str, Any]
) -> dict[str, Any]:
    """Compare two period snapshots for before/after analysis.

    Args:
        period1_data: First period metrics dict (e.g., from an earlier snapshot).
        period2_data: Second period metrics dict (e.g., from a later snapshot).

    Returns:
        Dict with metric-level comparisons: {metric: {before, after, change, improved}}.
    """
    comparisons: dict[str, dict[str, Any]] = {}

    all_keys = set(list(period1_data.keys()) + list(period2_data.keys()))
    for key in all_keys:
        before = period1_data.get(key)
        after = period2_data.get(key)
        if before is None or after is None:
            continue
        try:
            before_f = float(before)
            after_f = float(after)
            change = after_f - before_f
            pct = (change / before_f * 100) if before_f != 0 else 0.0
            comparisons[key] = {
                "before": before_f,
                "after": after_f,
                "change": round(change, 2),
                "pct_change": round(pct, 1),
                "improved": _is_improvement(key, before_f, after_f),
            }
        except (TypeError, ValueError):
            continue

    return comparisons
