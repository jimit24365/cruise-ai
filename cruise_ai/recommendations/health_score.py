"""cruise_ai.recommendations.health_score — compute an AI Health Score.

Provides:
- compute_health_score: returns a 0-100 composite score with breakdown
- detect: fires a recommendation when score < 60
"""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any

from cruise_ai.recommendations.types import Recommendation


def _compute_efficiency(sessions: list[Any], profile: dict[str, Any]) -> int:
    """Efficiency score (0-100) based on token waste and session length.

    Lower waste + reasonable session lengths = higher score.
    """
    if not sessions:
        return 50  # neutral default

    scores: list[float] = []

    # Factor 1: Token waste (prompt length vs optimal)
    all_word_counts: list[int] = []
    for s in sessions:
        wcs = getattr(s, "prompt_word_counts", None)
        if wcs is None and isinstance(s, dict):
            wcs = s.get("prompt_word_counts", [])
        if wcs:
            all_word_counts.extend(wcs)

    if all_word_counts:
        avg_words = statistics.mean(all_word_counts)
        # Optimal is ~100-200 words. Penalize above 400.
        if avg_words <= 200:
            scores.append(100.0)
        elif avg_words <= 400:
            scores.append(max(50.0, 100.0 - (avg_words - 200) * 0.25))
        else:
            scores.append(max(20.0, 100.0 - (avg_words - 200) * 0.15))

    # Factor 2: Session length optimization (turns per session)
    turn_counts: list[int] = []
    for s in sessions:
        user_msgs = getattr(s, "user_msgs", None)
        if user_msgs is None and isinstance(s, dict):
            user_msgs = s.get("user_msgs", 0)
        if user_msgs and user_msgs > 0:
            turn_counts.append(user_msgs)

    if turn_counts:
        avg_turns = statistics.mean(turn_counts)
        # Optimal is 5-15 turns. Penalize >25.
        if avg_turns <= 15:
            scores.append(100.0)
        elif avg_turns <= 25:
            scores.append(max(50.0, 100.0 - (avg_turns - 15) * 5))
        else:
            scores.append(max(20.0, 100.0 - (avg_turns - 15) * 3))

    if not scores:
        return 50
    return max(0, min(100, int(statistics.mean(scores))))


def _compute_diversity(sessions: list[Any], profile: dict[str, Any]) -> int:
    """Diversity score (0-100) based on model variety and tool variety."""
    scores: list[float] = []

    # Model variety
    model_set: set[str] = set()
    for s in sessions:
        models = getattr(s, "models", None)
        if models is None and isinstance(s, dict):
            models = s.get("models", [])
        if models:
            model_set.update(models)

    # Also pull from profile
    models_used = profile.get("models_used", [])
    if isinstance(models_used, list):
        model_set.update(models_used)

    model_count = len(model_set)
    if model_count == 0:
        scores.append(30.0)
    elif model_count == 1:
        scores.append(40.0)
    elif model_count == 2:
        scores.append(65.0)
    elif model_count == 3:
        scores.append(80.0)
    else:
        scores.append(100.0)

    # Tool variety
    tool_set: set[str] = set()
    for s in sessions:
        tools = getattr(s, "tool_calls_by_type", None)
        if tools is None and isinstance(s, dict):
            tools = s.get("tool_calls_by_type", {})
        if isinstance(tools, dict):
            tool_set.update(tools.keys())

    tools_used = profile.get("tools_used", [])
    if isinstance(tools_used, list):
        tool_set.update(tools_used)

    tool_count = len(tool_set)
    if tool_count <= 2:
        scores.append(30.0)
    elif tool_count <= 5:
        scores.append(55.0)
    elif tool_count <= 10:
        scores.append(75.0)
    else:
        scores.append(100.0)

    if not scores:
        return 50
    return max(0, min(100, int(statistics.mean(scores))))


def _compute_automation(profile: dict[str, Any], scan_results: dict[str, Any]) -> int:
    """Automation score (0-100) based on hooks, MCPs, skills configured."""
    configured = 0
    opportunities = 4  # hooks, MCPs, skills, config_files

    hooks = scan_results.get("hooks", [])
    if hooks:
        configured += 1

    mcps = scan_results.get("mcps", [])
    if mcps:
        configured += 1

    skills_list = scan_results.get("skills", [])
    if skills_list:
        configured += 1

    config_files = scan_results.get("config_files", [])
    if config_files:
        configured += 1

    # Scale: 0 configured = 20, all = 100
    if opportunities == 0:
        return 50
    ratio = configured / opportunities
    return max(0, min(100, int(20 + ratio * 80)))


def _compute_learning(sessions: list[Any], profile: dict[str, Any]) -> int:
    """Learning score (0-100) based on feedback engagement and recommendation adoption."""
    scores: list[float] = []

    # Check for feedback engagement (profile dimensions)
    dimensions = profile.get("dimensions", {})
    if isinstance(dimensions, dict):
        # Higher composite score generally means more engagement
        composite = profile.get("composite", 0)
        if isinstance(composite, (int, float)):
            # Normalize: 0-50 composite maps to 30-100 learning
            scores.append(min(100.0, 30.0 + composite * 1.4))

    # Check session count progression (more sessions = more learning)
    total_sessions = profile.get("total_sessions", len(sessions))
    if isinstance(total_sessions, (int, float)) and total_sessions > 0:
        if total_sessions >= 50:
            scores.append(90.0)
        elif total_sessions >= 20:
            scores.append(70.0)
        elif total_sessions >= 10:
            scores.append(55.0)
        else:
            scores.append(35.0)

    if not scores:
        return 50
    return max(0, min(100, int(statistics.mean(scores))))


def compute_health_score(
    sessions: list[Any],
    profile: dict[str, Any],
    scan_results: dict[str, Any],
) -> dict[str, Any]:
    """Compute an AI Health Score with breakdown.

    Args:
        sessions: List of session objects.
        profile: Profile dict.
        scan_results: Scan results dict.

    Returns:
        Dict with 'score' (0-100) and 'breakdown' dict with component scores.
    """
    try:
        profile = profile or {}
        scan_results = scan_results or {}

        efficiency = _compute_efficiency(sessions, profile)
        diversity = _compute_diversity(sessions, profile)
        automation = _compute_automation(profile, scan_results)
        learning = _compute_learning(sessions, profile)

        # Weighted average: efficiency most important
        score = int(
            efficiency * 0.35
            + diversity * 0.20
            + automation * 0.25
            + learning * 0.20
        )
        score = max(0, min(100, score))

        return {
            "score": score,
            "breakdown": {
                "efficiency": efficiency,
                "diversity": diversity,
                "automation": automation,
                "learning": learning,
            },
        }
    except Exception:
        return {
            "score": 50,
            "breakdown": {
                "efficiency": 50,
                "diversity": 50,
                "automation": 50,
                "learning": 50,
            },
        }


def _compute_health_from_normalized(norm: dict[str, Any], scan_results: dict[str, Any]) -> dict[str, Any]:
    """Compute health score from normalized signals when sessions aren't available."""
    avg_prompt_words = norm.get("avgPromptWords", 200)
    model_count = norm.get("modelCount", 1)
    unique_tool_count = norm.get("uniqueToolCount", 1)
    mcp_server_count = norm.get("mcpServerCount", 0)
    total_sessions = norm.get("totalSessions", 0)
    skills_list = scan_results.get("skills", [])
    hooks_list = scan_results.get("hooks", [])
    mcps_list = scan_results.get("mcps", [])

    # Efficiency from avg prompt words
    if avg_prompt_words <= 200:
        efficiency = 90
    elif avg_prompt_words <= 400:
        efficiency = max(50, 90 - int((avg_prompt_words - 200) * 0.2))
    else:
        efficiency = max(25, 90 - int((avg_prompt_words - 200) * 0.12))

    # Diversity from model and tool count
    model_score = min(100, 30 + model_count * 20)
    tool_score = min(100, 20 + unique_tool_count * 15)
    diversity = int((model_score + tool_score) / 2)

    # Automation from hooks, MCPs, skills
    configured = 0
    if hooks_list:
        configured += 1
    if mcps_list or mcp_server_count > 0:
        configured += 1
    if skills_list:
        configured += 1
    if scan_results.get("config_files"):
        configured += 1
    automation = max(0, min(100, int(20 + (configured / 4) * 80)))

    # Learning from total sessions
    if total_sessions >= 50:
        learning = 85
    elif total_sessions >= 20:
        learning = 65
    elif total_sessions >= 10:
        learning = 50
    else:
        learning = 35

    score = int(efficiency * 0.35 + diversity * 0.20 + automation * 0.25 + learning * 0.20)
    score = max(0, min(100, score))

    return {
        "score": score,
        "breakdown": {
            "efficiency": efficiency,
            "diversity": diversity,
            "automation": automation,
            "learning": learning,
        },
    }


def detect(
    sessions: list[Any], profile: dict[str, Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Fire a recommendation when AI Health Score < 60."""
    recs: list[Recommendation] = []
    try:
        norm = scan_results.get("normalized", {}) if scan_results else {}

        # Session-based health score
        if sessions and len(sessions) >= 5:
            result = compute_health_score(sessions, profile, scan_results)
        elif norm and norm.get("totalSessions", 0) >= 5:
            # Normalized-signal health score
            result = _compute_health_from_normalized(norm, scan_results)
        else:
            return recs

        score = result.get("score", 50)
        breakdown = result.get("breakdown", {})

        if score < 60:
            # Identify weakest area
            weakest = min(breakdown, key=lambda k: breakdown[k]) if breakdown else "efficiency"
            weakest_score = breakdown.get(weakest, 0)
            # Slightly lower confidence for normalized-based
            confidence = 67 if not sessions else 72

            recs.append(Recommendation(
                category="analytics",
                headline=f"AI Health Score is {score}/100 — focus on {weakest} ({weakest_score}/100)",
                detail=(
                    f"Your overall AI Health Score is {score}/100. "
                    f"Breakdown: efficiency={breakdown.get('efficiency', 0)}, "
                    f"diversity={breakdown.get('diversity', 0)}, "
                    f"automation={breakdown.get('automation', 0)}, "
                    f"learning={breakdown.get('learning', 0)}. "
                    f"The weakest area is '{weakest}' at {weakest_score}/100."
                ),
                action_type="improve_health_score",
                trust_level="heuristic",
                confidence=confidence,
                evidence=f"health score {score}/100, weakest: {weakest}={weakest_score}",
                priority="high" if score < 40 else "medium",
                teach_text=(
                    "The AI Health Score measures how effectively you use AI tools across "
                    "four dimensions:\n"
                    "- Efficiency: token usage and session management\n"
                    "- Diversity: variety of models and tools\n"
                    "- Automation: hooks, MCPs, and skills configured\n"
                    "- Learning: engagement and growth over time\n"
                    "Improving the weakest area gives the biggest boost."
                ),
                auto_action=f"Generate improvement plan focused on {weakest}",
                savings_estimate={"health_score": score, "target": 70},
            ))
    except Exception:
        pass

    return recs
