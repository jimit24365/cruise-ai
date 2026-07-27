"""cruise_ai.recommendations.project_memory — detect repeated context patterns.

Provides:
- Project Memory Recommendation: detect context that should be persistent
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from cruise_ai.recommendations.types import Recommendation


def _detect_project_concentration(sessions: list[Any]) -> list[Recommendation]:
    """Detect projects where context repetition is likely."""
    recs: list[Recommendation] = []
    if len(sessions) < 10:
        return recs

    # Count sessions per project
    project_sessions: dict[str, int] = defaultdict(int)
    project_prompts: dict[str, int] = defaultdict(int)
    project_words: dict[str, list[int]] = defaultdict(list)

    for s in sessions:
        proj = getattr(s, "project_path", None)
        if not proj:
            continue
        proj_name = proj.rstrip("/").split("/")[-1]
        project_sessions[proj_name] += 1
        project_prompts[proj_name] += getattr(s, "user_msgs", 0)
        project_words[proj_name].extend(getattr(s, "prompt_word_counts", []))

    if not project_sessions:
        return recs

    # Projects with many sessions likely need persistent memory
    for proj, session_count in project_sessions.items():
        if session_count < 5:
            continue

        total_words = sum(project_words.get(proj, []))
        avg_first_prompt = 0
        first_prompts = []
        for s in sessions:
            p = getattr(s, "project_path", "")
            if p and p.rstrip("/").split("/")[-1] == proj:
                wcs = getattr(s, "prompt_word_counts", [])
                if wcs:
                    first_prompts.append(wcs[0])

        if first_prompts:
            avg_first_prompt = sum(first_prompts) / len(first_prompts)

        # If avg first prompt is >100 words across many sessions, likely repeating context
        if avg_first_prompt > 100 and session_count >= 8:
            repeated_tokens = int(avg_first_prompt * 0.6 * 1.3 * session_count)
            recs.append(Recommendation(
                category="project_memory",
                headline=f"Project '{proj}' has {session_count} sessions with ~{avg_first_prompt:.0f}-word first prompts — needs project memory",
                detail=(
                    f"Across {session_count} sessions in '{proj}', the average first prompt is "
                    f"{avg_first_prompt:.0f} words. This suggests you're re-explaining project "
                    f"context each time. A project memory file (AGENTS.md, CLAUDE.md, or .kiro/steering/) "
                    f"would eliminate this repetition."
                ),
                action_type="create_project_memory",
                trust_level="observed",
                confidence=75 if session_count >= 12 else 65,
                evidence=f"{session_count} sessions, avg first prompt {avg_first_prompt:.0f} words in project '{proj}'",
                priority="high" if repeated_tokens > 30_000 else "medium",
                teach_text=(
                    "Project memory is persistent context your AI tool loads automatically:\n"
                    "- `.kiro/steering/*.md` — Kiro steering docs\n"
                    "- `CLAUDE.md` — Claude Code memory\n"
                    "- `.cursorrules` — Cursor rules\n"
                    "- `AGENTS.md` — Multi-agent project docs\n\n"
                    "Include: architecture decisions, coding standards, key file locations, "
                    "domain terminology, and project-specific patterns."
                ),
                auto_action=f"Analyze sessions in '{proj}' and generate a project memory template",
                savings_estimate={"tokens": repeated_tokens, "per_session": int(avg_first_prompt * 0.6 * 1.3)},
            ))
            break  # Only suggest for the top project

    return recs


def _detect_cross_session_patterns(sessions: list[Any]) -> list[Recommendation]:
    """Detect patterns that repeat across sessions regardless of project."""
    recs: list[Recommendation] = []
    if len(sessions) < 15:
        return recs

    # Check if the same tools are always configured together
    tool_sets: list[frozenset[str]] = []
    for s in sessions:
        tools = set(getattr(s, "tool_calls_by_type", {}).keys())
        if len(tools) >= 3:
            tool_sets.append(frozenset(tools))

    if len(tool_sets) < 10:
        return recs

    # Find the most common tool set pattern
    set_counter: Counter[frozenset[str]] = Counter(tool_sets)
    most_common_set, count = set_counter.most_common(1)[0]

    if count / len(tool_sets) > 0.5 and len(most_common_set) >= 4:
        tools_str = ", ".join(sorted(most_common_set)[:6])
        recs.append(Recommendation(
            category="project_memory",
            headline=f"Same tool configuration in {count}/{len(tool_sets)} sessions — create a workspace template",
            detail=(
                f"Tools [{tools_str}] appear together in {count} of {len(tool_sets)} sessions. "
                f"A workspace template or shared steering doc would standardize this setup."
            ),
            action_type="create_workspace_template",
            trust_level="heuristic",
            confidence=65,
            evidence=f"{count}/{len(tool_sets)} sessions share the tool set [{tools_str}]",
            priority="low",
            teach_text="When you always use the same tools together, a workspace template ensures consistent configuration without manual setup.",
        ))

    return recs


def _detect_memory_from_normalized(norm: dict[str, Any], scan_results: dict[str, Any]) -> list[Recommendation]:
    """Derive project memory recommendations from normalized scan signals."""
    recs: list[Recommendation] = []
    if not norm:
        return recs

    project_count = norm.get("projectCount", 0)
    deep_session_count = norm.get("deepSessionCount", 0)
    config_files = scan_results.get("config_files", [])

    # Check if memory config already exists
    has_memory = any(
        any(kw in str(f).lower() for kw in ["claude.md", "agents.md", "steering", ".cursorrules"])
        for f in config_files
    ) if config_files else False

    # projectCount > 10 AND no memory config -> recommend project memory
    if project_count > 10 and not has_memory:
        recs.append(Recommendation(
            category="project_memory",
            headline=f"{project_count} projects without memory config — set up project memory",
            detail=(
                f"You work across {project_count} projects but have no project memory "
                f"(CLAUDE.md, AGENTS.md, steering docs) configured. Without it, you re-explain "
                f"context every time you switch projects or start a new session."
            ),
            action_type="create_project_memory",
            trust_level="heuristic",
            confidence=68,
            evidence=f"{project_count} projects, no memory config detected (normalized)",
            priority="medium",
            teach_text=(
                "Project memory is persistent context your AI tool loads automatically:\n"
                "- `.kiro/steering/*.md` — Kiro steering docs\n"
                "- `CLAUDE.md` — Claude Code memory\n"
                "- `.cursorrules` — Cursor rules\n"
                "- `AGENTS.md` — Multi-agent project docs"
            ),
            auto_action="Generate project memory templates for your top projects",
        ))

    # deepSessionCount > 5 -> recommend session memory/context pinning
    if deep_session_count > 5:
        recs.append(Recommendation(
            category="project_memory",
            headline=f"{deep_session_count} deep sessions detected — pin recurring context to memory",
            detail=(
                f"You have {deep_session_count} deep sessions (many turns). Deep sessions "
                f"often mean you're providing lots of context manually. Pinning frequently-used "
                f"context to project memory would reduce setup time."
            ),
            action_type="create_project_memory",
            trust_level="heuristic",
            confidence=63,
            evidence=f"{deep_session_count} deep sessions (from scan normalized data)",
            priority="medium" if deep_session_count > 10 else "low",
            teach_text=(
                "Deep sessions (many turns) often accumulate context that should be persistent. "
                "Extract commonly-referenced files, patterns, and architecture into steering docs "
                "so they're always available without re-loading."
            ),
            auto_action="Analyze deep session patterns and suggest what to pin to memory",
        ))

    return recs


def detect(
    sessions: list[Any], profile: dict[str, Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Run all project memory detectors."""
    recs: list[Recommendation] = []

    # Session-based detection
    if sessions:
        recs.extend(_detect_project_concentration(sessions))
        recs.extend(_detect_cross_session_patterns(sessions))

    # Normalized-signal detection
    norm = scan_results.get("normalized", {}) if scan_results else {}
    if norm:
        recs.extend(_detect_memory_from_normalized(norm, scan_results))

    return recs
