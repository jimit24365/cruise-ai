"""cruise_ai.recommendations.learning — Teach Me / Do It For Me / Explain / Why This.

Provides:
- Teach Me: step-by-step tutorials based on detected opportunities
- Do It For Me: auto-generation capability markers
- Explain Changes: explain what generated artifacts do
- Why This?: explain why a recommendation was made
- Interactive Tutorials: structured multi-step guides
"""

from __future__ import annotations

from typing import Any

from cruise_ai.recommendations.types import Recommendation


# ---------------------------------------------------------------------------
# Interactive Tutorials
# ---------------------------------------------------------------------------

TUTORIALS: dict[str, dict[str, Any]] = {
    "create_skill": {
        "title": "Create Your First Skill",
        "steps": [
            {
                "instruction": "Create the skill directory structure under .kiro/skills/",
                "example": "mkdir -p .kiro/skills/my-skill && touch .kiro/skills/my-skill/SKILL.md",
                "validation": "Verify .kiro/skills/my-skill/SKILL.md exists",
            },
            {
                "instruction": "Define the skill metadata with name and activation triggers",
                "example": (
                    "# my-skill\n\n"
                    "Use when: Writing database queries; Optimizing SQL performance\n\n"
                    "## Instructions\n"
                    "- Always use parameterized queries\n"
                    "- Prefer CTEs over nested subqueries\n"
                    "- Add indexes for frequently filtered columns"
                ),
                "validation": "SKILL.md has a title, 'Use when:' section, and instructions",
            },
            {
                "instruction": "Add examples or patterns the AI should follow",
                "example": (
                    "## Examples\n\n"
                    "```sql\n"
                    "-- Good: parameterized\n"
                    "SELECT * FROM users WHERE id = $1;\n"
                    "-- Bad: string interpolation\n"
                    "SELECT * FROM users WHERE id = '{user_id}';\n"
                    "```"
                ),
                "validation": "Skill includes at least one concrete example with good/bad patterns",
            },
            {
                "instruction": "Test activation by starting a session related to the trigger topic",
                "example": "Ask the AI: 'Write a query to find inactive users' — skill should activate automatically",
                "validation": "AI mentions or applies the skill's patterns in its response",
            },
        ],
    },
    "create_mcp": {
        "title": "Set Up an MCP Server Connection",
        "steps": [
            {
                "instruction": "Identify the MCP server you want to connect (e.g., filesystem, database, API)",
                "example": "# Common MCP servers:\n# @modelcontextprotocol/server-filesystem\n# @modelcontextprotocol/server-github\n# @modelcontextprotocol/server-postgres",
                "validation": "You have chosen an MCP server package name",
            },
            {
                "instruction": "Add the MCP server configuration to your tool settings",
                "example": (
                    '# In .kiro/settings.json or mcp.json:\n'
                    '{\n'
                    '  "mcpServers": {\n'
                    '    "filesystem": {\n'
                    '      "command": "npx",\n'
                    '      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]\n'
                    '    }\n'
                    '  }\n'
                    '}'
                ),
                "validation": "MCP config file exists with valid JSON and server entry",
            },
            {
                "instruction": "Restart your AI tool to pick up the new MCP connection",
                "example": "Close and reopen Kiro/Claude/Cursor, or reload the window",
                "validation": "AI can call tools from the new MCP server",
            },
            {
                "instruction": "Test the MCP connection by asking the AI to use it",
                "example": "Ask: 'List files in my project root' (for filesystem MCP)",
                "validation": "AI successfully calls the MCP tool and returns results",
            },
        ],
    },
    "create_hook": {
        "title": "Create an Automation Hook",
        "steps": [
            {
                "instruction": "Identify a repetitive task you do after every code change (lint, test, format)",
                "example": "# Common hook targets:\n# - Run tests after file save\n# - Format code on commit\n# - Validate schema after model changes\n# - Update docs after API changes",
                "validation": "You have identified a specific repetitive task",
            },
            {
                "instruction": "Create the hook configuration file",
                "example": (
                    "# .kiro/hooks/post-edit.json:\n"
                    '{\n'
                    '  "trigger": "file_saved",\n'
                    '  "pattern": "*.py",\n'
                    '  "command": "python3 -m pytest tests/ -q --tb=short",\n'
                    '  "description": "Run tests after Python file changes"\n'
                    '}'
                ),
                "validation": "Hook config file exists with trigger, pattern, and command fields",
            },
            {
                "instruction": "Test the hook by triggering its condition",
                "example": "Edit a .py file and save — the hook should execute automatically",
                "validation": "Hook runs and produces output (pass or fail) without manual invocation",
            },
        ],
    },
    "optimize_prompts": {
        "title": "Optimize Your Prompting Patterns",
        "steps": [
            {
                "instruction": "Review your recent sessions for repeated context you provide manually",
                "example": "# Look for patterns like:\n# - Explaining your project structure every session\n# - Re-stating coding preferences\n# - Repeating 'use TypeScript', 'follow our patterns'",
                "validation": "You identified 2+ repeated context patterns across sessions",
            },
            {
                "instruction": "Move repeated context into steering docs or project memory",
                "example": (
                    "# .kiro/steering/project-context.md:\n"
                    "# Project Context\n\n"
                    "- TypeScript + React frontend\n"
                    "- Python FastAPI backend\n"
                    "- PostgreSQL database\n"
                    "- All APIs use OpenAPI specs in /docs/api/\n"
                    "- Test with pytest (backend) and vitest (frontend)"
                ),
                "validation": "Steering doc created and project context no longer repeated in prompts",
            },
            {
                "instruction": "Use structured prompts: objective + constraints + context",
                "example": (
                    "# Instead of:\n"
                    "#   'fix the login bug'\n"
                    "# Write:\n"
                    "#   'Fix: login returns 401 for valid tokens\n"
                    "#    Constraint: don't change the token format\n"
                    "#    Context: auth middleware in src/auth/middleware.ts'"
                ),
                "validation": "Next 3 prompts follow objective/constraint/context structure",
            },
            {
                "instruction": "Measure improvement: shorter prompts, fewer correction turns",
                "example": "Compare avg prompt length and turns-per-task before and after optimization",
                "validation": "Average prompt length decreased or task completion turns decreased",
            },
        ],
    },
    "setup_memory": {
        "title": "Set Up Project Memory",
        "steps": [
            {
                "instruction": "Create a CLAUDE.md or equivalent project memory file at your repo root",
                "example": (
                    "# CLAUDE.md\n\n"
                    "## Architecture\n"
                    "- Monorepo with apps/ and packages/ directories\n"
                    "- Shared types in packages/types/\n\n"
                    "## Conventions\n"
                    "- Use barrel exports (index.ts) for public APIs\n"
                    "- Error handling: Result<T, E> pattern, no thrown exceptions\n\n"
                    "## Key Commands\n"
                    "- `pnpm test` — run all tests\n"
                    "- `pnpm build` — production build"
                ),
                "validation": "Project memory file exists at repo root with architecture and conventions",
            },
            {
                "instruction": "Add decision records for important architectural choices",
                "example": (
                    "## Decisions\n"
                    "- 2024-03: Chose Drizzle over Prisma for type-safe SQL with better perf\n"
                    "- 2024-05: Moved to server components; client components only for interactivity\n"
                    "- 2024-06: Adopted Result pattern — all service functions return Result<T, AppError>"
                ),
                "validation": "At least 3 documented decisions with dates and rationale",
            },
            {
                "instruction": "Test that the AI uses project memory by asking about your architecture",
                "example": "Start a new session and ask: 'What ORM do we use and why?' — should answer from memory",
                "validation": "AI answers correctly without you re-explaining the context",
            },
        ],
    },
}


def list_tutorials() -> list[str]:
    """Return all available tutorial topic names."""
    return list(TUTORIALS.keys())


def get_tutorial(topic: str) -> dict[str, Any]:
    """Return the full tutorial for a given topic.

    Args:
        topic: Tutorial topic key (e.g. 'create_skill').

    Returns:
        Dict with 'title' and 'steps' list, or empty dict if topic not found.
    """
    return TUTORIALS.get(topic, {})


# ---------------------------------------------------------------------------
# Tutorial Opportunity Detection
# ---------------------------------------------------------------------------

def _detect_tutorial_opportunity(
    sessions: list[Any], profile: dict[str, Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Recommend tutorials when user is new to a concept.

    Checks scan_results and profile for absence of skills, MCPs, hooks, etc.
    and recommends the corresponding tutorial.
    """
    recs: list[Recommendation] = []

    try:
        skills_list = scan_results.get("skills", [])
        mcps_list = scan_results.get("mcps", [])
        hooks_list = scan_results.get("hooks", [])
        total_sessions = profile.get("total_sessions", len(sessions))

        # Need some minimum usage before recommending tutorials
        if total_sessions < 3:
            return recs

        # Only recommend when scan_results actually contains the relevant keys
        # (empty dict means no scan was performed — don't infer absence)
        has_scan_data = any(
            k in scan_results for k in ("skills", "mcps", "hooks", "tools_detected")
        )
        if not has_scan_data:
            return recs

        # No skills -> recommend create_skill tutorial
        if not skills_list:
            recs.append(Recommendation(
                category="learning",
                headline="Tutorial: Create your first skill to encode workflow patterns",
                detail=(
                    "Skills let you teach the AI your team's patterns, conventions, and "
                    "preferences so you don't have to repeat them every session. "
                    "No skills detected in your project."
                ),
                action_type="start_tutorial_create_skill",
                trust_level="validated",
                confidence=75,
                evidence=f"0 skills detected across {total_sessions} sessions",
                priority="medium",
                teach_text=TUTORIALS["create_skill"]["steps"][0]["instruction"],
                auto_action="Generate a starter skill based on your most common patterns",
            ))

        # No MCPs -> recommend create_mcp tutorial
        if not mcps_list:
            recs.append(Recommendation(
                category="learning",
                headline="Tutorial: Connect an MCP server to extend AI capabilities",
                detail=(
                    "MCP servers give the AI direct access to databases, APIs, file systems, "
                    "and more. No MCP connections detected in your setup."
                ),
                action_type="start_tutorial_create_mcp",
                trust_level="validated",
                confidence=75,
                evidence=f"0 MCP servers configured, {total_sessions} sessions without external tools",
                priority="medium",
                teach_text=TUTORIALS["create_mcp"]["steps"][0]["instruction"],
                auto_action="Suggest MCP servers based on your project stack",
            ))

        # No hooks -> recommend create_hook tutorial
        if not hooks_list:
            recs.append(Recommendation(
                category="learning",
                headline="Tutorial: Automate repetitive tasks with hooks",
                detail=(
                    "Hooks run commands automatically when certain events occur (file save, "
                    "commit, etc.). No automation hooks detected."
                ),
                action_type="start_tutorial_create_hook",
                trust_level="validated",
                confidence=75,
                evidence=f"0 hooks configured, manual workflow detected",
                priority="low",
                teach_text=TUTORIALS["create_hook"]["steps"][0]["instruction"],
                auto_action="Identify repetitive commands and generate hook configs",
            ))

        # High prompt verbosity -> recommend optimize_prompts tutorial
        tools_used = profile.get("tools_used", [])
        dimensions = profile.get("dimensions", {})
        prompt_efficiency = dimensions.get("prompt_efficiency", 100)
        if prompt_efficiency < 50 and total_sessions > 5:
            recs.append(Recommendation(
                category="learning",
                headline="Tutorial: Optimize your prompts for better results with fewer tokens",
                detail=(
                    f"Your prompt efficiency score is {prompt_efficiency}%. Structured prompts "
                    f"and context engineering can significantly reduce token usage while "
                    f"improving response quality."
                ),
                action_type="start_tutorial_optimize_prompts",
                trust_level="validated",
                confidence=75,
                evidence=f"Prompt efficiency {prompt_efficiency}% over {total_sessions} sessions",
                priority="medium",
                teach_text=TUTORIALS["optimize_prompts"]["steps"][0]["instruction"],
                auto_action="Analyze recent prompts and suggest restructuring",
            ))

        # No project memory files -> recommend setup_memory tutorial
        config_files = scan_results.get("config_files", [])
        has_memory = any(
            "CLAUDE.md" in str(f) or "AGENTS.md" in str(f) or "steering" in str(f)
            for f in config_files
        ) if config_files else False
        if not has_memory and total_sessions > 5:
            recs.append(Recommendation(
                category="learning",
                headline="Tutorial: Set up project memory so the AI remembers your context",
                detail=(
                    "Without project memory (CLAUDE.md, steering docs), you re-explain your "
                    "architecture, conventions, and preferences every session."
                ),
                action_type="start_tutorial_setup_memory",
                trust_level="validated",
                confidence=75,
                evidence=f"No project memory files found, {total_sessions} sessions",
                priority="medium",
                teach_text=TUTORIALS["setup_memory"]["steps"][0]["instruction"],
                auto_action="Generate a starter project memory file from your session history",
            ))

    except Exception:
        pass  # never crash

    return recs


# ---------------------------------------------------------------------------
# Existing Learning Opportunity Detectors
# ---------------------------------------------------------------------------

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


def _detect_learning_from_normalized(norm: dict[str, Any], scan_results: dict[str, Any]) -> list[Recommendation]:
    """Derive learning recommendations from normalized scan signals."""
    recs: list[Recommendation] = []
    if not norm:
        return recs

    total_sessions = norm.get("totalSessions", 0)
    plan_count = norm.get("planCount", 0)
    subagent_dispatches = norm.get("subagentDispatches", 0)

    # totalSessions < 20 -> beginner tutorials
    if 3 <= total_sessions < 20:
        recs.append(Recommendation(
            category="learning",
            headline="Getting started — structured tutorials available for AI-assisted development",
            detail=(
                f"With {total_sessions} sessions, you're in the early stages of AI-assisted "
                f"development. Tutorials on skills, MCP servers, and prompt optimization "
                f"can accelerate your workflow."
            ),
            action_type="start_tutorial_create_skill",
            trust_level="heuristic",
            confidence=65,
            evidence=f"{total_sessions} total sessions (from scan normalized data)",
            priority="medium",
            teach_text="Start with structured prompting and project memory to get the most from AI tools.",
            auto_action="Show beginner tutorial roadmap",
        ))

    # planCount == 0 AND totalSessions > 30 -> recommend plan mode
    if plan_count == 0 and total_sessions > 30:
        recs.append(Recommendation(
            category="learning",
            headline="No plan mode usage in 30+ sessions — try it for complex tasks",
            detail=(
                f"Across {total_sessions} sessions with 0 plan mode uses. Plan mode asks "
                f"the AI to outline steps before executing — catching misunderstandings before "
                f"they become multi-turn correction loops."
            ),
            action_type="teach_plan_mode",
            trust_level="heuristic",
            confidence=65,
            evidence=f"0 plan uses across {total_sessions} sessions (normalized)",
            priority="medium",
            teach_text=(
                "Plan mode lets the AI outline its approach before executing. "
                "Great for multi-file refactors, architecture changes, and complex features."
            ),
            auto_action="Enable plan mode for your next multi-file change",
        ))

    # subagentDispatches == 0 AND totalSessions > 50 -> recommend multi-agent
    if subagent_dispatches == 0 and total_sessions > 50:
        recs.append(Recommendation(
            category="learning",
            headline="50+ sessions without subagent usage — parallelize with multi-agent delegation",
            detail=(
                f"You have {total_sessions} sessions but haven't used subagent delegation. "
                f"Multi-step tasks (tests, docs, linting) can run in parallel via subagents "
                f"while you focus on the core work."
            ),
            action_type="teach_subagents",
            trust_level="heuristic",
            confidence=63,
            evidence=f"0 subagent dispatches, {total_sessions} sessions (normalized)",
            priority="medium",
            teach_text=(
                "Subagents run independent tasks in parallel — like having junior devs "
                "handle the boilerplate while you do the design."
            ),
            auto_action="Identify tasks suitable for subagent delegation",
        ))

    return recs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

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
    recs: list[Recommendation] = []

    # Session-based detection
    if sessions:
        recs.extend(_detect_learning_opportunities(sessions, profile))

    # Tutorial detection (uses scan_results primarily)
    recs.extend(_detect_tutorial_opportunity(sessions, profile, scan_results))

    # Normalized-signal detection
    norm = scan_results.get("normalized", {}) if scan_results else {}
    if norm:
        recs.extend(_detect_learning_from_normalized(norm, scan_results))

    return recs
