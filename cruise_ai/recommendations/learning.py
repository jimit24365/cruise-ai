"""cruise_ai.recommendations.learning — Teach Me / Do It For Me / Explain / Why This.

Provides:
- Teach Me: step-by-step tutorials based on detected opportunities
- Do It For Me: auto-generation capability markers
- Explain Changes: explain what generated artifacts do
- Why This?: explain why a recommendation was made
"""

from __future__ import annotations

from typing import Any

from cruise_ai.recommendations.types import Recommendation


def _detect_learning_opportunities(sessions: list[Any], profile: dict) -> list[Recommendation]:
    """Detect features the user isn't using that they could learn."""
    recs: list[Recommendation] = []
    total_sessions = len(sessions)
    if total_sessions < 10:
        return recs

    # Detect plan mode non-usage
    plan_pct = profile.get("wrappedStats", {}).get("planModePercent", 0)
    if plan_pct < 5 and total_sessions > 20:
        recs.append(Recommendation(
            category="learning",
            headline="You rarely use plan mode — it can reduce iteration cycles",
            detail=(
                f"Plan mode usage: {plan_pct:.1f}%. Plan mode lets the AI outline its "
                f"approach before executing — catching misunderstandings before they become "
                f"multi-turn correction loops. Especially valuable for multi-file changes."
            ),
            action_type="teach_plan_mode",
            trust_level="observed",
            confidence=70,
            evidence=f"Plan mode at {plan_pct:.1f}% over {total_sessions} sessions",
            priority="medium",
            teach_text=(
                "## Plan Mode\n\n"
                "Plan mode asks the AI to outline steps before executing:\n\n"
                "**How to use:**\n"
                "- Kiro: Start prompts with 'Plan:' or use /plan command\n"
                "- Claude Code: Use 'think first' or 'plan before acting'\n"
                "- Cursor: Use composer with 'outline the approach first'\n\n"
                "**When to use:**\n"
                "- Multi-file refactors\n"
                "- Architecture changes\n"
                "- Complex features with multiple steps\n"
                "- When you want to review the approach before execution\n\n"
                "**Result:** Fewer correction cycles, fewer wasted tokens on wrong approaches."
            ),
            auto_action="Enable plan mode for your next multi-file change",
        ))

    # Detect no subagent usage (learning opportunity)
    subagent_dispatches = profile.get("wrappedStats", {}).get("subagentDispatches", 0)
    if subagent_dispatches == 0 and total_sessions > 30:
        avg_turns = profile.get("wrappedStats", {}).get("avgPromptsPerSession", 0)
        if avg_turns > 10:
            recs.append(Recommendation(
                category="learning",
                headline="Learn: subagent delegation for parallel work",
                detail=(
                    f"With {avg_turns:.0f} avg turns/session and no subagent usage, "
                    f"you're doing everything sequentially. Subagents can parallelize "
                    f"independent tasks (tests, docs, formatting) while you work on the main task."
                ),
                action_type="teach_subagents",
            trust_level="heuristic",
                confidence=68,
                evidence=f"0 subagent dispatches, {avg_turns:.0f} avg turns across {total_sessions} sessions",
                priority="medium",
                teach_text=(
                    "## Subagent Delegation\n\n"
                    "Subagents are background tasks that run independently:\n\n"
                    "**Kiro:** `subagent` tool or pipeline stages\n"
                    "**Claude Code:** `dispatch` or `Task` tool\n\n"
                    "**Good delegation targets:**\n"
                    "- Writing unit tests for code you just wrote\n"
                    "- Updating documentation after a change\n"
                    "- Running linters/formatters\n"
                    "- Generating test fixtures\n"
                    "- Reviewing code for security issues\n\n"
                    "**Key principle:** Delegate tasks that don't need your input — "
                    "the subagent works while you continue on the main task."
                ),
                auto_action="Identify your next multi-step task and suggest which parts to delegate",
            ))

    # Detect context engineering opportunity
    avg_prompt_words = profile.get("wrappedStats", {}).get("avgPromptWords", 0)
    if avg_prompt_words > 80 and total_sessions > 20:
        recs.append(Recommendation(
            category="learning",
            headline="Learn: context engineering to reduce prompt overhead",
            detail=(
                f"Your avg prompt is {avg_prompt_words} words. With context engineering "
                f"(steering docs, rules files, pinned context), much of this becomes automatic."
            ),
            action_type="teach_context_engineering",
            trust_level="observed",
            confidence=65,
            evidence=f"Avg {avg_prompt_words} words/prompt over {total_sessions} sessions",
            priority="medium",
            teach_text=(
                "## Context Engineering\n\n"
                "Make the AI load your context automatically:\n\n"
                "| Tool | File | Purpose |\n"
                "|------|------|--------|\n"
                "| Kiro | `.kiro/steering/*.md` | Always-loaded context |\n"
                "| Kiro | `.kiro/skills/*/SKILL.md` | Reusable instruction sets |\n"
                "| Claude | `CLAUDE.md` | Project memory |\n"
                "| Cursor | `.cursorrules` | Custom instructions |\n"
                "| Any | `AGENTS.md` | Project architecture for AI |\n\n"
                "**What to put in them:**\n"
                "- Architecture decisions and patterns\n"
                "- Coding standards and conventions\n"
                "- Key file locations and their purposes\n"
                "- Domain terminology\n"
                "- Test patterns and expectations"
            ),
            auto_action="Analyze your prompts and generate steering doc suggestions",
        ))

    return recs


def explain_recommendation(rec: Recommendation) -> str:
    """Generate a 'Why This?' explanation for a recommendation.

    Returns a human-readable explanation string.
    """
    return (
        f"## Why This Recommendation?\n\n"
        f"**{rec.headline}**\n\n"
        f"### Evidence\n{rec.evidence}\n\n"
        f"### What We Detected\n{rec.detail}\n\n"
        f"### What You Can Do\n{rec.teach_text or 'See the recommendation detail above.'}\n\n"
        f"### Confidence: {rec.confidence}%\n"
        f"This recommendation is based on patterns observed across your sessions. "
        f"Higher confidence means stronger evidence from your actual usage."
    )


def detect(
    sessions: list[Any], profile: dict[str, Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Run all learning detectors."""
    return _detect_learning_opportunities(sessions, profile)
