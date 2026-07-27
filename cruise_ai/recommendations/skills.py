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


def _detect_skill_revision(sessions: list[Any], scan_results: dict[str, Any], profile: dict[str, Any] | None = None) -> list[Recommendation]:
    """Recommend skill revision when skills are stale but usage patterns have changed.

    If a skill file hasn't been modified in >30 days but related sessions show
    different patterns, recommend revision. Confidence is boosted when skills
    are part of mastered concepts in the learning path.
    """
    recs: list[Recommendation] = []
    skills_list = scan_results.get("skills", [])
    if not skills_list:
        return recs

    # Check for skills with modification timestamps
    stale_skills: list[str] = []
    for skill in skills_list:
        if isinstance(skill, dict):
            modified = skill.get("modified_days_ago", 0)
            name = skill.get("name", skill.get("path", "unknown"))
            if modified > 30:
                stale_skills.append(name)
        elif isinstance(skill, str):
            # String-only entries — can't determine age, skip
            continue

    if not stale_skills:
        return recs

    # Check if recent sessions show patterns different from what skills encode
    recent_tools: set[str] = set()
    for s in sessions[-20:] if len(sessions) > 20 else sessions:
        tools = getattr(s, "tool_calls_by_type", {})
        if isinstance(tools, dict):
            recent_tools.update(tools.keys())

    if stale_skills and recent_tools:
        # Boost confidence if skills concept is mastered in learning path
        base_confidence = 65
        try:
            from cruise_ai.recommendations.learning_path import _is_concept_mastered
            if profile and _is_concept_mastered("skills", sessions, profile, scan_results):
                base_confidence = 75  # higher weight for users who've mastered skills
        except Exception:
            pass

        recs.append(Recommendation(
            category="skills",
            headline=f"{len(stale_skills)} skill(s) unchanged for 30+ days — may need revision",
            detail=(
                f"Skills that haven't been updated may drift from your actual workflow. "
                f"Stale skills: {', '.join(stale_skills[:5])}. "
                f"Your recent sessions use tools ({', '.join(sorted(recent_tools)[:5])}) "
                f"that may have evolved beyond what these skills encode."
            ),
            action_type="revise_skill",
            trust_level="heuristic",
            confidence=base_confidence,
            evidence=f"{len(stale_skills)} skills >30 days old, {len(recent_tools)} tools in recent use",
            priority="low",
            teach_text=(
                "Skills should evolve with your workflow. When you change how you work "
                "(new tools, new patterns, new conventions) but your skills stay the same, "
                "they can give outdated instructions. Review stale skills periodically "
                "and update them to reflect current practices."
            ),
            auto_action="Compare stale skill instructions with recent session patterns and suggest updates",
        ))

    return recs


def _detect_skill_health(sessions: list[Any], scan_results: dict[str, Any]) -> list[Recommendation]:
    """Recommend cleanup when skills exist but aren't referenced in recent sessions.

    If scan_results.skills exist but none are referenced in recent sessions,
    they may be dead weight.
    """
    recs: list[Recommendation] = []
    skills_list = scan_results.get("skills", [])
    if not skills_list or len(sessions) < 5:
        return recs

    # Get skill names/paths
    skill_names: set[str] = set()
    for skill in skills_list:
        if isinstance(skill, dict):
            name = skill.get("name", skill.get("path", ""))
            if name:
                skill_names.add(name.lower())
        elif isinstance(skill, str):
            skill_names.add(skill.lower())

    if not skill_names:
        return recs

    # Check if any skills appear in recent session context
    referenced_skills: set[str] = set()
    recent_sessions = sessions[-30:] if len(sessions) > 30 else sessions
    for s in recent_sessions:
        context_files = getattr(s, "context_files", None)
        if context_files is None:
            if isinstance(s, dict):
                context_files = s.get("context_files", [])
            else:
                context_files = []
        for f in context_files:
            f_lower = str(f).lower() if f else ""
            for skill_name in skill_names:
                if skill_name in f_lower or f_lower.endswith("skill.md"):
                    referenced_skills.add(skill_name)

    unreferenced = skill_names - referenced_skills
    if unreferenced and len(unreferenced) == len(skill_names):
        recs.append(Recommendation(
            category="skills",
            headline=f"{len(unreferenced)} skill(s) exist but none referenced in recent sessions — consider cleanup",
            detail=(
                f"Found {len(skill_names)} configured skills but none appear in the "
                f"context of your last {len(recent_sessions)} sessions. "
                f"Unreferenced skills may be outdated or misconfigured. "
                f"Consider removing or updating: {', '.join(sorted(unreferenced)[:5])}"
            ),
            action_type="cleanup_skills",
            trust_level="heuristic",
            confidence=62,
            evidence=f"{len(unreferenced)}/{len(skill_names)} skills not referenced in {len(recent_sessions)} recent sessions",
            priority="low",
            teach_text=(
                "Skills that are never loaded provide no value and can create confusion. "
                "If your AI tool isn't picking up a skill, check:\n"
                "- Is it in the right location (.kiro/skills/, .cursor/rules/)?\n"
                "- Does it have the correct file name (SKILL.md)?\n"
                "- Is it relevant to your current projects?\n"
                "Remove skills you no longer use to keep your config clean."
            ),
            auto_action="Identify which skills are unused and suggest removal or relocation",
        ))

    return recs


def _detect_skill_merge(
    sessions: list[Any], profile: dict[str, Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Detect skills with >70% overlap in triggers/patterns, recommend merge.

    Compares skill triggers/tools/patterns pairwise. If two skills share
    more than 70% of their associated tools or context files, recommend merging.
    """
    recs: list[Recommendation] = []
    skills_list = scan_results.get("skills", [])
    if len(skills_list) < 2:
        return recs

    # Build skill -> associated tools/patterns mapping
    skill_patterns: dict[str, set[str]] = {}
    for skill in skills_list:
        if isinstance(skill, dict):
            name = skill.get("name", skill.get("path", ""))
            tools = set(skill.get("tools", []))
            triggers = set(skill.get("triggers", []))
            patterns = set(skill.get("patterns", []))
            combined = tools | triggers | patterns
            if name and combined:
                skill_patterns[name] = combined
        elif isinstance(skill, str):
            # String-only: try to infer from session context_files
            skill_patterns[skill] = set()

    # If we can't get patterns from scan_results, try to infer from sessions
    if all(len(v) == 0 for v in skill_patterns.values()):
        # Build skill -> context_files association from sessions
        for s in sessions:
            context_files = getattr(s, "context_files", None)
            if context_files is None and isinstance(s, dict):
                context_files = s.get("context_files", [])
            if not context_files:
                continue
            for f in context_files:
                f_str = str(f).lower() if f else ""
                for skill_name in skill_patterns:
                    if skill_name.lower() in f_str:
                        # Associate other context files with this skill
                        skill_patterns[skill_name].update(
                            str(cf) for cf in context_files if cf and str(cf) != str(f)
                        )

    # Pairwise overlap check
    skill_names = list(skill_patterns.keys())
    merge_candidates: list[tuple[str, str, float]] = []

    for i in range(len(skill_names)):
        for j in range(i + 1, len(skill_names)):
            s1 = skill_patterns[skill_names[i]]
            s2 = skill_patterns[skill_names[j]]
            if not s1 or not s2:
                continue
            intersection = s1 & s2
            union = s1 | s2
            if union:
                overlap = len(intersection) / len(union)
                if overlap > 0.7:
                    merge_candidates.append((skill_names[i], skill_names[j], overlap))

    if merge_candidates:
        # Report top merge candidate
        merge_candidates.sort(key=lambda x: -x[2])
        s1, s2, overlap = merge_candidates[0]
        recs.append(Recommendation(
            category="skills",
            headline=f"Skills '{s1}' and '{s2}' have {overlap*100:.0f}% overlap — consider merging",
            detail=(
                f"Skills '{s1}' and '{s2}' share {overlap*100:.0f}% of their "
                f"triggers/patterns/tools. Maintaining overlapping skills creates "
                f"confusion about which to apply. Merging into a single comprehensive "
                f"skill simplifies your configuration."
            ),
            action_type="merge_skills",
            trust_level="heuristic",
            confidence=68 if overlap > 0.8 else 63,
            evidence=f"{overlap*100:.0f}% overlap between '{s1}' and '{s2}'",
            priority="medium",
            teach_text=(
                "When two skills cover similar ground, they can conflict or create "
                "ambiguity about which applies. Merging them into one gives clearer, "
                "more consistent instructions to the AI."
            ),
            auto_action=f"Generate merged skill combining '{s1}' and '{s2}'",
        ))

    return recs


def _detect_skill_split(
    sessions: list[Any], profile: dict[str, Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Detect skills referenced in very different contexts, recommend split.

    If a single skill file is referenced across >3 unrelated projects,
    it's likely too broad and should be split into focused skills.
    """
    recs: list[Recommendation] = []
    skills_list = scan_results.get("skills", [])
    if not skills_list:
        return recs

    # Get skill names
    skill_names: list[str] = []
    for skill in skills_list:
        if isinstance(skill, dict):
            name = skill.get("name", skill.get("path", ""))
            if name:
                skill_names.append(name)
        elif isinstance(skill, str):
            skill_names.append(skill)

    if not skill_names:
        return recs

    # Track which projects each skill is used in
    skill_projects: dict[str, set[str]] = {name: set() for name in skill_names}

    for s in sessions:
        # Get project path
        project_path = getattr(s, "project_path", None)
        if project_path is None and isinstance(s, dict):
            project_path = s.get("project_path", "")
        if not project_path:
            continue

        # Get context files
        context_files = getattr(s, "context_files", None)
        if context_files is None and isinstance(s, dict):
            context_files = s.get("context_files", [])
        if not context_files:
            continue

        for f in context_files:
            f_str = str(f).lower() if f else ""
            for skill_name in skill_names:
                if skill_name.lower() in f_str or "skill" in f_str:
                    skill_projects[skill_name].add(str(project_path))

    # Check for skills used across >3 different projects
    for skill_name, projects in skill_projects.items():
        if len(projects) > 3:
            recs.append(Recommendation(
                category="skills",
                headline=f"Skill '{skill_name}' used across {len(projects)} projects — consider splitting",
                detail=(
                    f"The skill '{skill_name}' is referenced in {len(projects)} different "
                    f"project contexts. A skill spanning that many unrelated projects "
                    f"may be too broad. Splitting into focused, project-type-specific "
                    f"skills gives better, more relevant guidance."
                ),
                action_type="split_skill",
                trust_level="heuristic",
                confidence=65 if len(projects) > 4 else 63,
                evidence=f"'{skill_name}' referenced in {len(projects)} projects",
                priority="medium" if len(projects) > 4 else "low",
                teach_text=(
                    "A skill that applies everywhere may not be specific enough to help "
                    "anywhere. Consider splitting broad skills into focused variants:\n"
                    "- 'coding-standards' → 'python-standards', 'typescript-standards'\n"
                    "- 'testing' → 'unit-testing', 'integration-testing'\n"
                    "Each variant can give more precise, contextual guidance."
                ),
                auto_action=f"Analyze '{skill_name}' usage contexts and suggest split points",
            ))

    return recs


# ── Known community skills matching tool/workflow patterns ──
KNOWN_COMMUNITY_SKILLS: dict[str, dict[str, Any]] = {
    "testing": {
        "patterns": ["pytest", "jest", "mocha", "vitest", "test", "spec", "coverage"],
        "skill_name": "tdd-workflow",
        "description": "Test-Driven Development workflow with red-green-refactor patterns",
    },
    "deployment": {
        "patterns": ["docker", "kubernetes", "helm", "terraform", "deploy", "ci/cd", "pipeline"],
        "skill_name": "deployment-automation",
        "description": "Automated deployment pipelines with rollback safety",
    },
    "documentation": {
        "patterns": ["readme", "docs", "jsdoc", "docstring", "swagger", "typedoc", "markdown"],
        "skill_name": "auto-documentation",
        "description": "Auto-generate and maintain project documentation",
    },
    "refactoring": {
        "patterns": ["refactor", "extract", "rename", "move", "inline", "cleanup", "lint"],
        "skill_name": "safe-refactoring",
        "description": "Guided refactoring with automated verification steps",
    },
    "security": {
        "patterns": ["auth", "jwt", "oauth", "security", "encrypt", "credential", "secret"],
        "skill_name": "security-review",
        "description": "Automated security analysis and vulnerability detection",
    },
    "database": {
        "patterns": ["sql", "migration", "schema", "orm", "prisma", "sequelize", "typeorm"],
        "skill_name": "db-migration-safety",
        "description": "Safe database migrations with rollback plans",
    },
}


def _detect_skill_marketplace(
    sessions: list[Any], profile: dict[str, Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Recommend community skills based on user's tool/workflow patterns.

    Matches session activity against known community skill categories and
    recommends installation when patterns are strong.
    """
    recs: list[Recommendation] = []
    if not sessions or len(sessions) < 3:
        return recs

    # Collect all tool names and commands
    all_tools: list[str] = []
    all_commands: list[str] = []
    for s in sessions:
        if isinstance(s, dict):
            tool = s.get("tool_name", "")
            commands = s.get("commands", [])
        else:
            tool = getattr(s, "tool_name", "") or getattr(s, "tool", "")
            commands = getattr(s, "commands", []) or []
        if tool:
            all_tools.append(tool.lower())
        for cmd in commands:
            if isinstance(cmd, str):
                all_commands.append(cmd.lower())

    # Also check existing skills to avoid recommending what's already installed
    existing_skills = set()
    skills_data = scan_results.get("skills", [])
    for skill in skills_data:
        if isinstance(skill, str):
            existing_skills.add(skill.lower())
        elif isinstance(skill, dict):
            existing_skills.add(skill.get("name", "").lower())

    # Match patterns to community skills
    combined_text = " ".join(all_tools + all_commands)
    for category, info in KNOWN_COMMUNITY_SKILLS.items():
        skill_name = info["skill_name"]
        if skill_name.lower() in existing_skills:
            continue

        pattern_matches = sum(
            1 for p in info["patterns"] if p in combined_text
        )
        if pattern_matches >= 2:
            recs.append(Recommendation(
                category="skills",
                headline=f"Your {category} patterns match the '{skill_name}' community skill",
                detail=(
                    f"Detected {pattern_matches} {category}-related patterns in your sessions. "
                    f"The '{skill_name}' community skill provides: {info['description']}. "
                    f"Installing it would give your AI tool specialized guidance for {category} tasks."
                ),
                action_type="install_community_skill",
                trust_level="heuristic",
                confidence=63,
                evidence=f"{pattern_matches} pattern matches for '{category}' category",
                priority="low",
                teach_text=(
                    "Community skills are pre-built instruction sets shared by the community. "
                    "They encode best practices for specific workflows (testing, deployment, etc.) "
                    "so your AI tool knows HOW to approach these tasks correctly without you "
                    "having to explain the workflow each time."
                ),
                auto_action=f"Install the '{skill_name}' community skill",
                savings_estimate={"skill_name": skill_name, "category": category},
            ))

    return recs


def _detect_from_normalized(norm: dict[str, Any], scan_results: dict[str, Any]) -> list[Recommendation]:
    """Derive skill recommendations from normalized scan signals."""
    recs: list[Recommendation] = []
    if not norm:
        return recs

    total_sessions = norm.get("totalSessions", 0)
    unique_tool_count = norm.get("uniqueToolCount", 0)
    skills_list = scan_results.get("skills", [])

    # No skills AND totalSessions > 20 -> create first skill
    if not skills_list and total_sessions > 20:
        recs.append(Recommendation(
            category="skills",
            headline="No skills configured after 20+ sessions — create your first skill",
            detail=(
                f"You have {total_sessions} sessions but no skills configured. "
                f"Skills encode your workflow patterns so the AI follows them automatically "
                f"without you re-explaining each session."
            ),
            action_type="create_skill",
            trust_level="heuristic",
            confidence=70,
            evidence=f"0 skills, {total_sessions} sessions (from scan normalized data)",
            priority="medium",
            teach_text=(
                "A Skill is a reusable instruction set that tells your AI tool HOW to use "
                "specific tools or follow specific patterns. Instead of re-explaining your "
                "workflow each session, a Skill encodes it permanently."
            ),
            auto_action="Generate a starter skill based on your most-used tool patterns",
        ))

    # uniqueToolCount >= 2 AND no skills -> recommend skill for tool patterns
    if unique_tool_count >= 2 and not skills_list and total_sessions > 10:
        recs.append(Recommendation(
            category="skills",
            headline=f"Using {unique_tool_count} AI tools without skills — encode tool patterns",
            detail=(
                f"You use {unique_tool_count} different AI tools across {total_sessions} sessions. "
                f"Without skills, you're likely re-explaining your preferences to each tool. "
                f"A skill file standardizes how tools interact with your code."
            ),
            action_type="create_skill",
            trust_level="heuristic",
            confidence=65,
            evidence=f"{unique_tool_count} tools, 0 skills (normalized scan data)",
            priority="medium",
            teach_text="Skills provide consistent instructions across tools — create one per workflow pattern.",
            auto_action="Generate skills based on detected tool usage patterns",
        ))

    # Skill marketplace: if totalSessions > 30, recommend community skills based on stack
    if total_sessions > 30 and not skills_list:
        stack = scan_results.get("stack", [])
        stack_text = " ".join(str(s).lower() for s in stack) if stack else ""
        for category, info in KNOWN_COMMUNITY_SKILLS.items():
            pattern_matches = sum(1 for p in info["patterns"] if p in stack_text)
            if pattern_matches >= 2:
                recs.append(Recommendation(
                    category="skills",
                    headline=f"Your stack matches the '{info['skill_name']}' community skill",
                    detail=(
                        f"Detected {pattern_matches} {category}-related patterns in your tech stack. "
                        f"The '{info['skill_name']}' community skill provides: {info['description']}."
                    ),
                    action_type="install_community_skill",
                    trust_level="heuristic",
                    confidence=58,
                    evidence=f"{pattern_matches} stack pattern matches for '{category}' (normalized)",
                    priority="low",
                    teach_text=(
                        "Community skills are pre-built instruction sets shared by the community. "
                        "They encode best practices for specific workflows."
                    ),
                    auto_action=f"Install the '{info['skill_name']}' community skill",
                    savings_estimate={"skill_name": info["skill_name"], "category": category},
                ))
                break  # Only suggest one community skill

    return recs


def detect(
    sessions: list[Any], profile: dict[str, Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Run all skill detectors."""
    recs: list[Recommendation] = []

    # Session-based detection
    if sessions:
        recs.extend(_detect_tool_patterns(sessions))
        recs.extend(_detect_underutilized_tools(sessions))
        recs.extend(_detect_skill_revision(sessions, scan_results, profile))
        recs.extend(_detect_skill_health(sessions, scan_results))
        recs.extend(_detect_skill_merge(sessions, profile, scan_results))
        recs.extend(_detect_skill_split(sessions, profile, scan_results))
        recs.extend(_detect_skill_marketplace(sessions, profile, scan_results))

    # Normalized-signal detection
    norm = scan_results.get("normalized", {}) if scan_results else {}
    if norm:
        recs.extend(_detect_from_normalized(norm, scan_results))

    return recs
