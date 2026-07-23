"""cruise_ai.recommendations.feedback — user feedback on recommendations.

Stores feedback locally at ~/.cruise-ai/data/feedback.json.
Tracks: which recommendations were acted on, dismissed, or found useful.
Used to adjust confidence over time and avoid repeating stale suggestions.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _feedback_path() -> Path:
    """Return path to feedback storage file."""
    from cruise_ai.paths import data_dir
    return data_dir() / "feedback.json"


def _load_feedback() -> list[dict[str, Any]]:
    """Load existing feedback entries."""
    path = _feedback_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_feedback(entries: list[dict[str, Any]]) -> None:
    """Persist feedback entries."""
    path = _feedback_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2))


def record_feedback(
    action_type: str,
    category: str,
    response: str,
    headline: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Record user feedback on a recommendation.

    Args:
        action_type: The recommendation's action_type (e.g. "compress_prompts")
        category: The recommendation category (e.g. "token_optimization")
        response: One of "acted", "dismissed", "useful", "not_useful"
        headline: The recommendation headline (for reference)
        notes: Optional free-text user notes

    Returns:
        The recorded feedback entry.
    """
    entry = {
        "action_type": action_type,
        "category": category,
        "response": response,
        "headline": headline,
        "notes": notes,
        "timestamp": time.time(),
        "date": time.strftime("%Y-%m-%d"),
    }

    entries = _load_feedback()
    entries.append(entry)
    _save_feedback(entries)
    return entry


def get_feedback_summary() -> dict[str, Any]:
    """Summarize all feedback.

    Returns:
        Dict with counts by response type and by category.
    """
    entries = _load_feedback()
    if not entries:
        return {"total": 0, "by_response": {}, "by_category": {}}

    by_response: dict[str, int] = {}
    by_category: dict[str, dict[str, int]] = {}

    for e in entries:
        resp = e.get("response", "unknown")
        cat = e.get("category", "unknown")
        by_response[resp] = by_response.get(resp, 0) + 1
        if cat not in by_category:
            by_category[cat] = {}
        by_category[cat][resp] = by_category[cat].get(resp, 0) + 1

    return {
        "total": len(entries),
        "by_response": by_response,
        "by_category": by_category,
    }


def get_dismissed_action_types() -> set[str]:
    """Get action_types the user has dismissed — used to suppress repeats."""
    entries = _load_feedback()
    dismissed = set()
    acted = set()

    for e in entries:
        at = e.get("action_type", "")
        resp = e.get("response", "")
        if resp == "dismissed":
            dismissed.add(at)
        elif resp == "acted":
            acted.add(at)

    # If acted later, remove from dismissed
    return dismissed - acted


def confidence_adjustment(action_type: str) -> int:
    """Get confidence adjustment for an action_type based on feedback.

    Returns:
        Positive = boost, negative = penalize, 0 = no change.
    """
    entries = _load_feedback()
    acted_count = 0
    dismissed_count = 0
    useful_count = 0
    not_useful_count = 0

    for e in entries:
        if e.get("action_type") != action_type:
            continue
        resp = e.get("response", "")
        if resp == "acted":
            acted_count += 1
        elif resp == "dismissed":
            dismissed_count += 1
        elif resp == "useful":
            useful_count += 1
        elif resp == "not_useful":
            not_useful_count += 1

    # Positive signals boost, negative signals penalize
    return (acted_count * 5 + useful_count * 3) - (dismissed_count * 3 + not_useful_count * 5)
