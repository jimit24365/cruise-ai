"""cruise_ai.recommendations.analytics — usage, cost, and timeline insights.

Provides:
- AI Usage Dashboard: daily/weekly usage, tokens, models, repositories
- Cost Dashboard: token & cost estimation
- Timeline: AI activity timeline
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from cruise_ai.recommendations.types import Recommendation

# Approximate cost per 1K tokens by model family (USD, blended input/output)
MODEL_COSTS_PER_1K: dict[str, float] = {
    "claude-opus": 0.030,
    "claude-sonnet": 0.006,
    "claude-haiku": 0.001,
    "gpt-4o": 0.010,
    "gpt-4": 0.040,
    "gpt-3.5": 0.001,
    "o1": 0.030,
    "o3": 0.020,
    "gemini-pro": 0.004,
    "gemini-flash": 0.001,
    "deepseek": 0.002,
}


def _estimate_tokens_from_words(word_count: int) -> int:
    """Approximate tokens from word count (1 word ≈ 1.3 tokens)."""
    return int(word_count * 1.3)


def _match_model_cost(model_name: str) -> float:
    """Match a model name to its approximate cost tier."""
    name = model_name.lower()
    for prefix, cost in MODEL_COSTS_PER_1K.items():
        if prefix.replace("-", "") in name.replace("-", ""):
            return cost
    return 0.006  # default to sonnet-tier if unknown


def _compute_usage_stats(sessions: list[Any], profile: dict) -> dict[str, Any]:
    """Compute usage statistics from sessions and profile."""
    total_sessions = len(sessions)
    total_user_msgs = sum(getattr(s, "user_msgs", 0) for s in sessions)
    total_assistant_msgs = sum(getattr(s, "assistant_msgs", 0) for s in sessions)

    # Prompt tokens
    all_prompt_words = []
    for s in sessions:
        all_prompt_words.extend(getattr(s, "prompt_word_counts", []))
    total_prompt_words = sum(all_prompt_words)
    total_prompt_tokens = _estimate_tokens_from_words(total_prompt_words)

    # Response tokens estimate (assistant msgs typically 3-5x longer than prompts)
    avg_prompt_words = total_prompt_words / max(len(all_prompt_words), 1)
    estimated_response_tokens = _estimate_tokens_from_words(
        int(total_assistant_msgs * avg_prompt_words * 4)
    )

    # Models
    model_counts: dict[str, int] = defaultdict(int)
    for s in sessions:
        for m in getattr(s, "models", []):
            model_counts[m] += 1
    # Also from profile
    models_summary = profile.get("modelsSummary", {}).get("byModel", {})
    for m, count in models_summary.items():
        if m not in model_counts:
            model_counts[m] = count

    # Tools
    tool_counts: dict[str, int] = defaultdict(int)
    for s in sessions:
        tool_counts[getattr(s, "tool", "unknown")] += 1

    # Projects
    project_counts: dict[str, int] = defaultdict(int)
    for s in sessions:
        proj = getattr(s, "project_path", None)
        if proj:
            # Use just the last path component
            project_counts[proj.rstrip("/").split("/")[-1]] += 1

    # Daily activity
    daily: dict[str, dict] = defaultdict(lambda: {"sessions": 0, "prompts": 0, "minutes": 0})
    for s in sessions:
        dt = getattr(s, "started_at", None)
        if dt:
            day = dt.strftime("%Y-%m-%d")
            daily[day]["sessions"] += 1
            daily[day]["prompts"] += getattr(s, "user_msgs", 0)

    return {
        "total_sessions": total_sessions,
        "total_user_msgs": total_user_msgs,
        "total_assistant_msgs": total_assistant_msgs,
        "total_prompt_tokens": total_prompt_tokens,
        "estimated_response_tokens": estimated_response_tokens,
        "total_tokens": total_prompt_tokens + estimated_response_tokens,
        "models": dict(model_counts),
        "tools": dict(tool_counts),
        "projects": dict(project_counts),
        "daily": dict(daily),
        "avg_prompt_words": int(avg_prompt_words),
        "all_prompt_words": all_prompt_words,
    }


def _compute_cost(stats: dict[str, Any]) -> dict[str, Any]:
    """Estimate costs based on model usage and token counts."""
    models = stats.get("models", {})
    total_tokens = stats.get("total_tokens", 0)

    if not models:
        # Can't attribute cost without model info
        avg_cost = 0.006  # assume sonnet-tier
        total_cost = (total_tokens / 1000) * avg_cost
        return {"total_estimated_cost_usd": round(total_cost, 2), "by_model": {}}

    # Distribute tokens proportionally across models
    total_model_sessions = sum(models.values())
    cost_by_model: dict[str, float] = {}
    total_cost = 0.0

    for model_name, count in models.items():
        proportion = count / max(total_model_sessions, 1)
        model_tokens = int(total_tokens * proportion)
        cost_per_1k = _match_model_cost(model_name)
        model_cost = (model_tokens / 1000) * cost_per_1k
        cost_by_model[model_name] = round(model_cost, 2)
        total_cost += model_cost

    return {
        "total_estimated_cost_usd": round(total_cost, 2),
        "by_model": cost_by_model,
        "tokens_total": total_tokens,
    }


def detect(
    sessions: list[Any], profile: dict[str, Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Detect analytics-related recommendations."""
    recs: list[Recommendation] = []
    if not sessions:
        return recs

    stats = _compute_usage_stats(sessions, profile)
    cost = _compute_cost(stats)

    # ── Usage Dashboard insight: high usage without cost awareness ──
    if stats["total_tokens"] > 500_000:
        recs.append(Recommendation(
            category="analytics",
            headline=f"You've used ~{stats['total_tokens']:,} tokens across {stats['total_sessions']} sessions",
            detail=(
                f"Estimated cost: ${cost['total_estimated_cost_usd']:.2f}. "
                f"Top model: {max(stats['models'], key=stats['models'].get) if stats['models'] else 'unknown'}. "
                f"Run `cruise-ai dashboard` for the full breakdown."
            ),
            action_type="view_dashboard",
            trust_level="heuristic",
            confidence=90,
            evidence=f"{stats['total_sessions']} sessions, {stats['total_user_msgs']} prompts analyzed",
            priority="medium",
            teach_text="Token usage directly correlates with cost. Understanding your usage patterns helps optimize spending.",
            savings_estimate={"tokens": 0, "cost_usd": cost["total_estimated_cost_usd"]},
        ))

    # ── Cost insight: expensive model overuse ──
    if cost.get("by_model"):
        expensive_models = {
            m: c for m, c in cost["by_model"].items()
            if _match_model_cost(m) >= 0.020
        }
        cheap_models = {
            m: c for m, c in cost["by_model"].items()
            if _match_model_cost(m) <= 0.005
        }
        if expensive_models and cheap_models:
            expensive_pct = sum(
                stats["models"].get(m, 0) for m in expensive_models
            ) / max(sum(stats["models"].values()), 1) * 100
            if expensive_pct > 60:
                potential_savings = sum(expensive_models.values()) * 0.7
                recs.append(Recommendation(
                    category="analytics",
                    headline=f"{expensive_pct:.0f}% of sessions use expensive models — routing could save ${potential_savings:.2f}",
                    detail=(
                        f"Models like {', '.join(list(expensive_models.keys())[:2])} cost "
                        f"${list(expensive_models.values())[0]:.2f}+. "
                        f"For routine tasks (formatting, simple edits), a cheaper model would suffice."
                    ),
                    action_type="model_routing",
                    trust_level="observed",
                    confidence=75,
                    evidence=f"{expensive_pct:.0f}% of {sum(stats['models'].values())} sessions use premium models",
                    priority="medium",
                    teach_text="Not every task needs the most powerful model. Simple tasks (formatting, typo fixes, boilerplate) work equally well with faster, cheaper models.",
                    auto_action="Suggest model routing rules based on task complexity",
                    savings_estimate={"cost_usd": round(potential_savings, 2)},
                ))

    # ── Timeline insight: weekend/late-night patterns ──
    daily = stats.get("daily", {})
    if len(daily) >= 14:
        # Check for weekend activity
        weekend_days = 0
        total_days = 0
        for date_str, day_data in daily.items():
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                total_days += 1
                if dt.weekday() >= 5:  # Saturday=5, Sunday=6
                    weekend_days += 1
            except ValueError:
                pass

        if total_days > 0 and weekend_days / total_days > 0.3:
            recs.append(Recommendation(
                category="analytics",
                headline=f"{weekend_days}/{total_days} active days are weekends — high engagement",
                detail="You're actively using AI tools on weekends, suggesting either high engagement or work-life balance opportunity.",
                action_type="view_timeline",
                trust_level="heuristic",
                confidence=70,
                evidence=f"{weekend_days} weekend days out of {total_days} total active days",
                priority="low",
                teach_text="Consistent usage patterns (including rest days) correlate with sustained productivity.",
            ))

    return recs


def dashboard(sessions: list[Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Generate the full dashboard data structure for display.

    Returns a dict with keys: usage, cost, timeline, models, projects.
    """
    stats = _compute_usage_stats(sessions, profile)
    cost = _compute_cost(stats)

    return {
        "usage": {
            "total_sessions": stats["total_sessions"],
            "total_prompts": stats["total_user_msgs"],
            "total_responses": stats["total_assistant_msgs"],
            "total_tokens_estimated": stats["total_tokens"],
            "avg_prompt_words": stats["avg_prompt_words"],
        },
        "cost": cost,
        "models": stats["models"],
        "projects": stats["projects"],
        "tools": stats["tools"],
        "daily": stats["daily"],
    }
