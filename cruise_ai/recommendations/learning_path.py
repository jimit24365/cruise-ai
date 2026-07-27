"""cruise_ai.recommendations.learning_path — AI Learning Path progression system.

Tracks user mastery of AI-assisted development concepts and recommends
next learning steps based on demonstrated session evidence.
"""

from __future__ import annotations

from typing import Any

from cruise_ai.recommendations.types import Recommendation


# ---------------------------------------------------------------------------
# Concept Definitions & Mastery Criteria
# ---------------------------------------------------------------------------

CONCEPTS: list[str] = [
    "basic_prompting",
    "tool_usage",
    "skills",
    "mcps",
    "hooks",
    "memory",
    "eval_harness",
    "multi_model",
    "automation",
]

LEVELS: list[tuple[str, int, int]] = [
    ("beginner", 0, 2),
    ("intermediate", 3, 5),
    ("advanced", 6, 8),
    ("expert", 9, 9),  # all concepts mastered
]


def _classify_level(mastered_count: int) -> str:
    """Determine level based on number of mastered concepts."""
    for level_name, low, high in LEVELS:
        if low <= mastered_count <= high:
            return level_name
    return "expert"


def _is_concept_mastered(
    concept: str,
    sessions: list[Any],
    profile: dict[str, Any],
    scan_results: dict[str, Any],
) -> bool:
    """Determine if a concept is mastered based on session evidence.

    Each concept has specific evidence thresholds that indicate proficiency.
    """
    try:
        total_sessions = profile.get("total_sessions", len(sessions))
        tools_used = profile.get("tools_used", [])
        models_used = profile.get("models_used", [])
        dimensions = profile.get("dimensions", {})
        skills_list = scan_results.get("skills", [])
        mcps_list = scan_results.get("mcps", [])
        hooks_list = scan_results.get("hooks", [])
        config_files = scan_results.get("config_files", [])

        if concept == "basic_prompting":
            # Mastered if user has 10+ sessions (they know how to prompt)
            return total_sessions >= 10

        elif concept == "tool_usage":
            # Mastered if user uses 3+ distinct tools regularly
            return len(tools_used) >= 3

        elif concept == "skills":
            # Mastered if user has 3+ skills and total sessions > 10
            return len(skills_list) >= 3 and total_sessions > 10

        elif concept == "mcps":
            # Mastered if user has 2+ MCP servers configured
            return len(mcps_list) >= 2

        elif concept == "hooks":
            # Mastered if user has 2+ hooks configured
            return len(hooks_list) >= 2

        elif concept == "memory":
            # Mastered if project memory files exist (CLAUDE.md, steering docs, etc.)
            memory_indicators = ["CLAUDE.md", "AGENTS.md", "steering", ".cursorrules"]
            has_memory = any(
                any(indicator in str(f) for indicator in memory_indicators)
                for f in config_files
            ) if config_files else False
            return has_memory

        elif concept == "eval_harness":
            # Mastered if user has evaluation/testing infrastructure
            # Evidence: dimensions show test coverage or eval-related tools used
            has_eval = dimensions.get("test_coverage", 0) > 60
            eval_tools = ["pytest", "vitest", "jest", "eval", "benchmark"]
            uses_eval_tools = any(
                any(t in str(tool).lower() for t in eval_tools)
                for tool in tools_used
            )
            return has_eval or uses_eval_tools

        elif concept == "multi_model":
            # Mastered if user has used 3+ different models
            return len(models_used) >= 3

        elif concept == "automation":
            # Mastered if hooks + skills + MCPs all present (fully automated workflow)
            return (
                len(hooks_list) >= 1
                and len(skills_list) >= 2
                and len(mcps_list) >= 1
                and total_sessions >= 20
            )

    except Exception:
        pass  # never crash

    return False


# ---------------------------------------------------------------------------
# Learning Path Computation
# ---------------------------------------------------------------------------

def compute_learning_path(
    sessions: list[Any],
    profile: dict[str, Any],
    scan_results: dict[str, Any],
) -> dict[str, Any]:
    """Compute the user's current learning path state.

    Args:
        sessions: List of session dicts/objects.
        profile: User profile dict.
        scan_results: Project scan results dict.

    Returns:
        Dict with current_level, completed_topics, next_topics, progress_pct.
    """
    try:
        completed: list[str] = []
        remaining: list[str] = []

        for concept in CONCEPTS:
            if _is_concept_mastered(concept, sessions, profile, scan_results):
                completed.append(concept)
            else:
                remaining.append(concept)

        mastered_count = len(completed)
        total_count = len(CONCEPTS)
        current_level = _classify_level(mastered_count)
        progress_pct = int((mastered_count / total_count) * 100) if total_count > 0 else 0

        # Next topics: first 3 unmastered concepts (ordered by CONCEPTS list priority)
        next_topics = remaining[:3]

        return {
            "current_level": current_level,
            "completed_topics": completed,
            "next_topics": next_topics,
            "progress_pct": progress_pct,
        }

    except Exception:
        return {
            "current_level": "beginner",
            "completed_topics": [],
            "next_topics": CONCEPTS[:3],
            "progress_pct": 0,
        }


# ---------------------------------------------------------------------------
# Concept-to-Action Mapping
# ---------------------------------------------------------------------------

_CONCEPT_RECOMMENDATIONS: dict[str, dict[str, str]] = {
    "basic_prompting": {
        "headline": "Learning Path: Master structured prompting for better AI responses",
        "detail": (
            "Start with structured prompts (objective + constraints + context) to get "
            "more precise responses with fewer correction turns."
        ),
    },
    "tool_usage": {
        "headline": "Learning Path: Explore more AI tools to find your optimal workflow",
        "detail": (
            "Try different tools (file search, code analysis, terminal) to build a "
            "comprehensive toolkit. More tools = more ways the AI can help."
        ),
    },
    "skills": {
        "headline": "Learning Path: Create skills to encode your team's patterns",
        "detail": (
            "Skills let you teach the AI your conventions once and reuse them forever. "
            "Create skills for your most repeated instructions."
        ),
    },
    "mcps": {
        "headline": "Learning Path: Connect MCP servers for richer AI context",
        "detail": (
            "MCP servers give the AI direct access to your databases, APIs, and services. "
            "Start with filesystem or GitHub MCP."
        ),
    },
    "hooks": {
        "headline": "Learning Path: Automate repetitive tasks with hooks",
        "detail": (
            "Hooks run commands automatically on events (save, commit, etc.). "
            "Automate your lint/test/format cycle."
        ),
    },
    "memory": {
        "headline": "Learning Path: Set up project memory for persistent context",
        "detail": (
            "Project memory (CLAUDE.md, steering docs) means the AI knows your "
            "architecture and conventions without you re-explaining every session."
        ),
    },
    "eval_harness": {
        "headline": "Learning Path: Build an evaluation harness to measure AI quality",
        "detail": (
            "An eval harness lets you systematically test AI outputs against "
            "expected results. Critical for production-quality AI-assisted code."
        ),
    },
    "multi_model": {
        "headline": "Learning Path: Use multiple models for different task types",
        "detail": (
            "Different models excel at different tasks. Use fast models for simple "
            "edits, powerful models for architecture, specialized models for code review."
        ),
    },
    "automation": {
        "headline": "Learning Path: Build end-to-end AI automation pipelines",
        "detail": (
            "Combine skills + hooks + MCPs into automated workflows where the AI "
            "handles entire task chains with minimal intervention."
        ),
    },
}


def _compute_level_from_normalized(norm: dict[str, Any], scan_results: dict[str, Any]) -> dict[str, Any]:
    """Compute learning path from normalized signals when sessions aren't available."""
    completed: list[str] = []
    remaining: list[str] = []

    total_sessions = norm.get("totalSessions", 0)
    mcp_server_count = norm.get("mcpServerCount", 0)
    model_count = norm.get("modelCount", 0)
    unique_tool_count = norm.get("uniqueToolCount", 0)
    skills_list = scan_results.get("skills", [])
    mcps_list = scan_results.get("mcps", [])
    hooks_list = scan_results.get("hooks", [])
    config_files = scan_results.get("config_files", [])

    # basic_prompting: mastered if 10+ sessions
    if total_sessions >= 10:
        completed.append("basic_prompting")
    else:
        remaining.append("basic_prompting")

    # tool_usage: mastered if 3+ unique tools
    if unique_tool_count >= 3:
        completed.append("tool_usage")
    else:
        remaining.append("tool_usage")

    # skills: mastered if 3+ skills
    if len(skills_list) >= 3:
        completed.append("skills")
    else:
        remaining.append("skills")

    # mcps: mastered if 2+ MCP servers
    if len(mcps_list) >= 2 or mcp_server_count >= 2:
        completed.append("mcps")
    else:
        remaining.append("mcps")

    # hooks: mastered if 2+ hooks
    if len(hooks_list) >= 2:
        completed.append("hooks")
    else:
        remaining.append("hooks")

    # memory: mastered if project memory files exist
    memory_indicators = ["CLAUDE.md", "AGENTS.md", "steering", ".cursorrules"]
    has_memory = any(
        any(ind in str(f) for ind in memory_indicators)
        for f in config_files
    ) if config_files else False
    if has_memory:
        completed.append("memory")
    else:
        remaining.append("memory")

    # eval_harness: hard to determine from normalized alone
    remaining.append("eval_harness")

    # multi_model: mastered if 3+ models
    if model_count >= 3:
        completed.append("multi_model")
    else:
        remaining.append("multi_model")

    # automation: mastered if hooks + skills + MCPs all present
    if (len(hooks_list) >= 1 and len(skills_list) >= 2 and
            (len(mcps_list) >= 1 or mcp_server_count >= 1) and total_sessions >= 20):
        completed.append("automation")
    else:
        remaining.append("automation")

    mastered_count = len(completed)
    total_count = len(CONCEPTS)
    current_level = _classify_level(mastered_count)
    progress_pct = int((mastered_count / total_count) * 100) if total_count > 0 else 0
    next_topics = remaining[:3]

    return {
        "current_level": current_level,
        "completed_topics": completed,
        "next_topics": next_topics,
        "progress_pct": progress_pct,
    }


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

def detect(
    sessions: list[Any],
    profile: dict[str, Any],
    scan_results: dict[str, Any],
) -> list[Recommendation]:
    """Recommend next learning step based on current learning path level.

    Returns at most one recommendation for the highest-priority unmastered concept.
    """
    recs: list[Recommendation] = []

    try:
        norm = scan_results.get("normalized", {}) if scan_results else {}

        # Compute path from sessions or normalized data
        if sessions:
            path = compute_learning_path(sessions, profile, scan_results)
        elif norm and norm.get("totalSessions", 0) >= 3:
            path = _compute_level_from_normalized(norm, scan_results)
        else:
            return recs

        next_topics = path.get("next_topics", [])
        current_level = path.get("current_level", "beginner")
        progress_pct = path.get("progress_pct", 0)

        # Need minimum sessions before recommending learning path
        total_sessions = profile.get("total_sessions", len(sessions)) if sessions else norm.get("totalSessions", 0)
        if total_sessions < 3:
            return recs

        if not next_topics:
            return recs  # expert level, nothing to recommend

        # Recommend the first unmastered concept
        next_concept = next_topics[0]
        rec_info = _CONCEPT_RECOMMENDATIONS.get(next_concept, {})

        if rec_info:
            # Slightly lower confidence for normalized-based
            confidence = 67 if not sessions else 72
            recs.append(Recommendation(
                category="learning",
                headline=rec_info["headline"],
                detail=(
                    f"{rec_info['detail']} "
                    f"(Level: {current_level}, progress: {progress_pct}%)"
                ),
                action_type="advance_learning_path",
                trust_level="observed",
                confidence=confidence,
                evidence=(
                    f"Learning path: {current_level} ({progress_pct}% complete). "
                    f"Next concept: {next_concept}"
                ),
                priority="medium",
                teach_text=(
                    f"Your current level: **{current_level}** ({progress_pct}% complete)\n\n"
                    f"Next step: master **{next_concept.replace('_', ' ')}**\n\n"
                    f"{rec_info['detail']}"
                ),
                auto_action=f"Guide you through mastering {next_concept.replace('_', ' ')}",
            ))

    except Exception:
        pass  # never crash

    return recs
