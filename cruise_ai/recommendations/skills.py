"""cruise_ai.recommendations.skills — detect opportunities for reusable Skills.

Provides:
- Skill Recommendation: detect repeated tool patterns that could be Skills
- Skill Generator: produce structured Skill files
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from cruise_ai.recommendations.types import Recommendation


def _detect_tool_patterns(sessions: list[Any]) -> list[Recommendation]:
    """Detect repeated tool usage patterns that could become Skills."""
    recs: list[Recommendation] = []
    if len(sessions) < 10:
        return recs

    # Aggregate tool usage across sessions
    tool_totals: Counter[str] = Counter()
    sessions_with_tool: dict[str, int] = defaultdict(int)

    for s in sessions:
        tools = getattr(s, "tool_calls_by_type", {})
        for tool_name, count in tools.items():
            tool_totals[tool_name] += count
            sessions_with_tool[tool_name] += 1

    if not tool_totals:
        return recs

    # Detect tools used in >60% of sessions (candidates for steering docs)
    total_sessions = len(sessions)
    frequent_tools = [
        (tool, sessions_with_tool[tool])
        for tool in sessions_with_tool
        if sessions_with_tool[tool] / total_sessions > 0.6
        and tool not in {"read", "write", "shell", "grep", "glob"}  # exclude basics
    ]

    if frequent_tools:
        tool_names = [t[0] for t in sorted(frequent_tools, key=lambda x: -x[1])[:5]]
        recs.append(Recommendation(
            category="skills",
            headline=f"Tools {', '.join(tool_names[:3])} used in 60%+ of sessions — consider a Skill",
            detail=(
                f"These tools appear consistently across most of your sessions: "
                f"{', '.join(f'{t} ({sessions_with_tool[t]}/{total_sessions} sessions)' for t in tool_names[:5])}. "
                f"A Skill file would standardize how these are used and reduce setup prompts."
            ),
            action_type="create_skill",
            trust_level="heuristic",
            confidence=72,
            evidence=f"{len(frequent_tools)} tools used in >60% of {total_sessions} sessions",
            priority="medium",
            teach_text=(
                "A Skill is a reusable instruction set that tells your AI tool HOW to use "
                "specific tools or follow specific patterns. Instead of re-explaining your "
                "workflow each session, a Skill encodes it permanently."
            ),
            auto_action="Generate a Skill file based on your most-used tool combinations",
        ))

    # Detect tool combinations that always appear together (co-occurrence)
    co_occurrences: Counter[tuple[str, str]] = Counter()
    for s in sessions:
        tools = sorted(set(getattr(s, "tool_calls_by_type", {}).keys()))
        for i, t1 in enumerate(tools):
            for t2 in tools[i + 1:]:
                co_occurrences[(t1, t2)] += 1

    # Find pairs that appear together in >50% of sessions they appear in individually
    for (t1, t2), together_count in co_occurrences.most_common(10):
        min_individual = min(sessions_with_tool[t1], sessions_with_tool[t2])
        if min_individual >= 5 and together_count / min_individual > 0.7:
            if t1 in {"read", "write", "shell", "grep", "glob"}:
                continue
            if t2 in {"read", "write", "shell", "grep", "glob"}:
                continue
            recs.append(Recommendation(
                category="skills",
                headline=f"{t1} + {t2} always used together — bundle into a Skill",
                detail=(
                    f"These tools co-occur in {together_count} sessions "
                    f"({together_count/min_individual*100:.0f}% co-occurrence rate). "
                    f"A combined Skill could streamline this workflow."
                ),
                action_type="create_skill",
            trust_level="heuristic",
                confidence=68,
                evidence=f"{together_count}/{min_individual} sessions use both {t1} and {t2}",
                priority="medium",
                teach_text="When tools are always used together, a Skill can encode the entire workflow — reducing prompts and ensuring consistency.",
                auto_action=f"Generate a Skill file that combines {t1} and {t2} usage patterns",
            ))
            break  # Only suggest the top co-occurrence

    return recs


def _detect_underutilized_tools(sessions: list[Any]) -> list[Recommendation]:
    """Detect tools available but rarely used."""
    recs: list[Recommendation] = []
    if len(sessions) < 10:
        return recs

    tool_totals: Counter[str] = Counter()
    for s in sessions:
        tools = getattr(s, "tool_calls_by_type", {})
        for tool_name, count in tools.items():
            tool_totals[tool_name] += count

    total_calls = sum(tool_totals.values())
    if total_calls < 50:
        return recs

    # Check for heavy grep usage without glob (common pattern)
    grep_count = tool_totals.get("grep", 0) + tool_totals.get("search", 0)
    glob_count = tool_totals.get("glob", 0) + tool_totals.get("find_files", 0)
    if grep_count > 20 and glob_count == 0:
        recs.append(Recommendation(
            category="skills",
            headline="Heavy search usage but no file discovery — try glob/find for batch discovery",
            detail=(
                f"You use grep/search {grep_count} times but never use glob/find_files. "
                f"For discovering which files to look at, glob is faster (one call vs many greps)."
            ),
            action_type="adopt_tool",
            trust_level="observed",
            confidence=65,
            evidence=f"{grep_count} grep/search calls, 0 glob/find_files calls",
            priority="low",
            teach_text="grep finds content IN files. glob finds which FILES match a pattern. Using both together is faster: glob to find candidates, grep to search within them.",
        ))

    # Check for no subagent usage (missed delegation opportunity)
    task_calls = tool_totals.get("task", 0) + tool_totals.get("dispatch", 0)
    total_sessions = len(sessions)
    avg_user_msgs = sum(getattr(s, "user_msgs", 0) for s in sessions) / max(total_sessions, 1)

    if task_calls == 0 and avg_user_msgs > 15 and total_sessions > 20:
        recs.append(Recommendation(
            category="skills",
            headline="No subagent delegation — your sessions avg 15+ turns, consider dispatching",
            detail=(
                f"Avg {avg_user_msgs:.0f} user messages per session across {total_sessions} sessions, "
                f"but no subagent/task dispatches. Multi-step tasks (test writing, docs, linting) "
                f"can run in parallel via subagents while you focus on the core work."
            ),
            action_type="try_subagent_dispatch",
            trust_level="heuristic",
            confidence=68,
            evidence=f"0 subagent dispatches, {avg_user_msgs:.0f} avg turns/session over {total_sessions} sessions",
            priority="medium",
            teach_text=(
                "Subagents run independent tasks in parallel — like having junior devs handle "
                "the boilerplate while you do the design. Great for: writing tests, updating docs, "
                "running linters, generating fixtures."
            ),
            auto_action="Identify which recurring tasks in your sessions could be delegated to subagents",
        ))

    return recs


def generate_skill(name: str, description: str, tools: list[str], pattern: str) -> str:
    """Generate a complete Skill file content.

    Returns a SKILL.md file content string.
    """
    return f"""# {name}

{description}

## When to Use
- When working with: {', '.join(tools)}
- {pattern}

## Instructions

When this skill is active:

1. Always use the following tool sequence: {' → '.join(tools)}
2. {pattern}

## Tools Required
{chr(10).join(f'- `{t}`' for t in tools)}
"""


def detect(
    sessions: list[Any], profile: dict[str, Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Run all skill detectors."""
    recs: list[Recommendation] = []
    recs.extend(_detect_tool_patterns(sessions))
    recs.extend(_detect_underutilized_tools(sessions))
    return recs
