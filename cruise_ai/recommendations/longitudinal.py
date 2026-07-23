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
