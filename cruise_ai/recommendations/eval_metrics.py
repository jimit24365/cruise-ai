"""cruise_ai.recommendations.eval_metrics — precision/recall measurement for detectors.

This is a measurement tool, not a detector. It evaluates how well the
recommendation system performs by analyzing feedback data and session patterns.
"""

from __future__ import annotations

from typing import Any


def compute_precision(feedback_data: list[dict[str, Any]]) -> float:
    """Compute precision: ratio of positive outcomes to total feedback.

    Positive outcomes are 'acted' or 'useful' responses.
    Precision answers: "Of the recommendations we showed, how many were good?"

    Args:
        feedback_data: List of feedback entries (from feedback._load_feedback()).

    Returns:
        Float 0.0–1.0. Returns 0.0 if no feedback.
    """
    if not feedback_data:
        return 0.0

    positive = sum(
        1 for f in feedback_data if f.get("response") in ("acted", "useful")
    )
    return positive / len(feedback_data)


def compute_recall_proxy(
    sessions: list[Any],
    recommendations: list[Any],
) -> float:
    """Estimate recall: how many opportunities were detected vs missed.

    This is a proxy — true recall requires ground truth. We estimate by
    looking at session patterns that *should* have triggered recommendations
    but didn't.

    Heuristic indicators of missed opportunities:
    - Sessions with >500 prompt words but no token_optimization rec
    - Sessions using single model with many tool calls but no skills rec
    - Sessions with repeated context but no project_memory rec

    Args:
        sessions: List of Session-like objects.
        recommendations: List of Recommendation objects from engine.

    Returns:
        Float 0.0–1.0 estimating detection coverage. Returns 1.0 if no
        detectable opportunities exist.
    """
    if not sessions:
        return 1.0

    # Count detectable opportunity signals in sessions
    opportunities = 0
    detected = 0

    rec_categories = {r.category for r in recommendations} if recommendations else set()
    rec_action_types = {r.action_type for r in recommendations} if recommendations else set()

    for session in sessions:
        prompt_words = getattr(session, "prompt_word_counts", []) or []

        # Opportunity: long prompts should trigger token optimization
        if prompt_words and max(prompt_words, default=0) > 500:
            opportunities += 1
            if "token_optimization" in rec_categories:
                detected += 1

        # Opportunity: many tool calls should trigger skills suggestion
        tool_calls = getattr(session, "tool_calls_by_type", {}) or {}
        total_tools = sum(tool_calls.values()) if tool_calls else 0
        if total_tools > 20:
            opportunities += 1
            if "skills" in rec_categories:
                detected += 1

        # Opportunity: repeated project should trigger project memory
        extras = getattr(session, "extras", {}) or {}
        if extras.get("repeated_context_count", 0) > 3:
            opportunities += 1
            if "project_memory" in rec_categories:
                detected += 1

    if opportunities == 0:
        return 1.0

    return detected / opportunities


def per_detector_metrics(
    feedback_data: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Compute precision and stats per action_type (detector).

    Args:
        feedback_data: List of feedback entries.

    Returns:
        Dict mapping action_type to:
        {
            "precision": float,
            "recall_proxy": float (placeholder — needs session data),
            "total_feedback": int,
            "useful_count": int,
        }
    """
    if not feedback_data:
        return {}

    by_action: dict[str, list[dict[str, Any]]] = {}
    for entry in feedback_data:
        action_type = entry.get("action_type", "unknown")
        if action_type not in by_action:
            by_action[action_type] = []
        by_action[action_type].append(entry)

    result: dict[str, dict[str, Any]] = {}
    for action_type, entries in by_action.items():
        useful_count = sum(
            1 for e in entries if e.get("response") in ("acted", "useful")
        )
        total = len(entries)
        result[action_type] = {
            "precision": useful_count / total if total > 0 else 0.0,
            "recall_proxy": 0.0,  # requires session data — use compute_recall_proxy separately
            "total_feedback": total,
            "useful_count": useful_count,
        }

    return result
