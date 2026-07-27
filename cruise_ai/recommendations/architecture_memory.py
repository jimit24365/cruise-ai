"""cruise_ai.recommendations.architecture_memory — detect need for architecture docs.

Provides:
- detect: recommend ARCHITECTURE.md, AGENTS.md, CLAUDE.md generation
- generate_architecture_doc: produce outline for ARCHITECTURE.md
- generate_agents_md: produce AGENTS.md template
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from cruise_ai.recommendations.types import Recommendation

# Keywords that indicate architecture-related work
_ARCHITECTURE_KEYWORDS = {
    "import", "module", "class", "interface", "abstract",
    "service", "controller", "repository", "handler", "middleware",
    "layer", "boundary", "dependency", "inject", "factory",
    "pattern", "architecture", "structure", "design", "refactor",
}

# Keywords that indicate AI tool usage
_AI_TOOL_KEYWORDS = {
    "claude", "kiro", "copilot", "cursor", "codewhisperer",
    "ai", "llm", "agent", "assistant", "prompt",
}


def _detect_architecture_doc_need(
    sessions: list[Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Recommend ARCHITECTURE.md when sessions repeatedly reference architecture patterns.

    If sessions show architecture-related work (imports, class structures, module
    boundaries) without corresponding documentation, suggest generating docs.
    """
    recs: list[Recommendation] = []
    if not sessions or len(sessions) < 5:
        return recs

    # Check if architecture docs already exist
    config_files = scan_results.get("config_files", [])
    existing_docs = set()
    for f in config_files:
        f_str = str(f).lower() if f else ""
        if "architecture" in f_str:
            existing_docs.add("architecture")
        if "agents" in f_str:
            existing_docs.add("agents")
        if "claude" in f_str:
            existing_docs.add("claude")

    if "architecture" in existing_docs:
        return recs  # Already has architecture docs

    # Count architecture-related patterns in sessions
    arch_session_count = 0
    for s in sessions:
        # Check commands for architecture keywords
        commands = getattr(s, "commands", None)
        if commands is None and isinstance(s, dict):
            commands = s.get("commands", [])
        if not commands:
            commands = []

        # Check context files for architecture patterns
        context_files = getattr(s, "context_files", None)
        if context_files is None and isinstance(s, dict):
            context_files = s.get("context_files", [])
        if not context_files:
            context_files = []

        has_arch_signal = False

        # Check context files for architecture-related paths
        for f in context_files:
            f_str = str(f).lower() if f else ""
            if any(kw in f_str for kw in ["src/", "lib/", "pkg/", "internal/", "domain/"]):
                has_arch_signal = True
                break

        # Check commands for architecture keywords
        if not has_arch_signal:
            for cmd in commands:
                cmd_str = str(cmd).lower() if cmd else ""
                if any(kw in cmd_str for kw in _ARCHITECTURE_KEYWORDS):
                    has_arch_signal = True
                    break

        if has_arch_signal:
            arch_session_count += 1

    arch_pct = arch_session_count / len(sessions) * 100

    if arch_pct > 40:
        recs.append(Recommendation(
            category="skills",
            headline="Frequent architecture work without docs — generate ARCHITECTURE.md",
            detail=(
                f"{arch_session_count} of {len(sessions)} sessions ({arch_pct:.0f}%) "
                f"involve architecture-related work (module boundaries, imports, class structures) "
                f"but no ARCHITECTURE.md was found. An architecture doc helps AI tools understand "
                f"your codebase structure without re-explaining it each session."
            ),
            action_type="generate_architecture_doc",
            trust_level="heuristic",
            confidence=70 if arch_pct > 60 else 65,
            evidence=f"{arch_session_count}/{len(sessions)} sessions show architecture patterns",
            priority="medium",
            teach_text=(
                "ARCHITECTURE.md documents your codebase's high-level structure: "
                "modules, layers, key abstractions, and boundaries. AI tools load "
                "this automatically to understand where to make changes without "
                "needing you to explain the structure each time."
            ),
            auto_action="Generate ARCHITECTURE.md based on project scan results",
        ))

    return recs


def _detect_agents_md_need(
    sessions: list[Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Recommend AGENTS.md/CLAUDE.md when AI tool usage detected without config.

    If sessions show AI tool usage but no AGENTS.md or CLAUDE.md exists,
    recommend creating them for better AI tool configuration.
    """
    recs: list[Recommendation] = []
    if not sessions or len(sessions) < 3:
        return recs

    # Check what config files exist
    config_files = scan_results.get("config_files", [])
    has_agents = False
    has_claude = False
    for f in config_files:
        f_str = str(f).lower() if f else ""
        if "agents.md" in f_str:
            has_agents = True
        if "claude.md" in f_str:
            has_claude = True

    if has_agents and has_claude:
        return recs  # Both exist

    # Detect AI tool usage from sessions
    ai_tool_sessions = 0
    tools_detected: set[str] = set()
    for s in sessions:
        tool = getattr(s, "tool", None)
        if tool is None and isinstance(s, dict):
            tool = s.get("tool_name", s.get("tool", ""))
        if tool:
            tool_lower = str(tool).lower()
            if any(kw in tool_lower for kw in _AI_TOOL_KEYWORDS):
                ai_tool_sessions += 1
                tools_detected.add(str(tool))

    # Also check scan_results for tools_detected
    scan_tools = scan_results.get("tools_detected", [])
    for t in scan_tools:
        t_str = str(t).lower() if t else ""
        if any(kw in t_str for kw in _AI_TOOL_KEYWORDS):
            tools_detected.add(str(t))

    # If we have sessions at all, they're from AI tools
    if len(sessions) >= 3:
        ai_tool_sessions = max(ai_tool_sessions, len(sessions))

    if ai_tool_sessions < 3 and not tools_detected:
        return recs

    if not has_agents:
        recs.append(Recommendation(
            category="skills",
            headline="AI tool usage detected without AGENTS.md — create one for better context",
            detail=(
                f"Detected {ai_tool_sessions} sessions with AI tools "
                f"({', '.join(sorted(tools_detected)[:3]) or 'various'}) "
                f"but no AGENTS.md found. AGENTS.md tells AI tools about your project's "
                f"conventions, architecture, and preferences — reducing setup prompts."
            ),
            action_type="generate_agents_md",
            trust_level="heuristic",
            confidence=67,
            evidence=f"{ai_tool_sessions} AI sessions, no AGENTS.md found",
            priority="medium",
            teach_text=(
                "AGENTS.md is a project-level instruction file that AI coding tools read "
                "automatically. It documents: project structure, conventions, common commands, "
                "and things the AI should know. This eliminates repeating context every session."
            ),
            auto_action="Generate AGENTS.md template based on project scan",
        ))

    if not has_claude:
        recs.append(Recommendation(
            category="skills",
            headline="No CLAUDE.md found — create one for Claude-based tools",
            detail=(
                f"Detected AI tool usage but no CLAUDE.md. This file configures "
                f"Claude-based tools (Claude Code, Kiro) with project-specific instructions, "
                f"permissions, and conventions."
            ),
            action_type="generate_claude_md",
            trust_level="heuristic",
            confidence=65,
            evidence=f"AI tool usage detected, no CLAUDE.md found",
            priority="low",
            teach_text=(
                "CLAUDE.md is read by Claude Code and Kiro at the start of every session. "
                "It can include: allowed commands, project conventions, file patterns to avoid, "
                "and custom instructions. It's your persistent instruction set for Claude."
            ),
            auto_action="Generate CLAUDE.md template based on project scan",
        ))

    return recs


def generate_architecture_doc(scan_results: dict[str, Any]) -> dict[str, Any]:
    """Generate a suggested ARCHITECTURE.md content outline.

    Args:
        scan_results: The scan results dict.

    Returns:
        Dict with 'title', 'sections' list, and 'suggested_content' string.
    """
    try:
        projects = scan_results.get("projects", [])
        stack = scan_results.get("stack", [])
        summary = scan_results.get("summary", {})

        sections = [
            {"heading": "Overview", "description": "High-level description of the project's purpose and architecture."},
            {"heading": "Directory Structure", "description": "Key directories and their responsibilities."},
            {"heading": "Core Modules", "description": "Primary modules/packages and their roles."},
            {"heading": "Data Flow", "description": "How data moves through the system."},
            {"heading": "Key Abstractions", "description": "Important interfaces, base classes, and patterns."},
            {"heading": "Dependencies", "description": "External dependencies and why they're used."},
            {"heading": "Development Workflow", "description": "Build, test, and deploy commands."},
        ]

        # Enrich based on scan_results
        if stack:
            sections.append({
                "heading": "Technology Stack",
                "description": f"Built with: {', '.join(str(s) for s in stack[:10])}.",
            })

        suggested_content = "# Architecture\n\n"
        for section in sections:
            suggested_content += f"## {section['heading']}\n\n{section['description']}\n\n"

        return {
            "title": "ARCHITECTURE.md",
            "sections": sections,
            "suggested_content": suggested_content,
            "stack": stack[:10] if stack else [],
            "projects": [str(p) for p in projects[:5]] if projects else [],
        }
    except Exception:
        return {
            "title": "ARCHITECTURE.md",
            "sections": [],
            "suggested_content": "# Architecture\n\n<!-- Add your architecture documentation here -->\n",
        }


def generate_agents_md(scan_results: dict[str, Any]) -> dict[str, Any]:
    """Generate an AGENTS.md template based on scan results.

    Args:
        scan_results: The scan results dict.

    Returns:
        Dict with 'title', 'sections', and 'suggested_content'.
    """
    try:
        stack = scan_results.get("stack", [])
        tools_detected = scan_results.get("tools_detected", [])
        projects = scan_results.get("projects", [])

        sections = [
            {"heading": "Project Overview", "description": "What this project does and its primary language/framework."},
            {"heading": "Code Conventions", "description": "Style guide, naming conventions, import ordering."},
            {"heading": "Common Commands", "description": "Build, test, lint, and deploy commands."},
            {"heading": "Architecture Notes", "description": "Key patterns and boundaries to respect."},
            {"heading": "Forbidden Patterns", "description": "Things the AI should never do in this project."},
        ]

        suggested_content = "# AGENTS.md\n\n"
        suggested_content += "## Project Overview\n\n"
        if stack:
            suggested_content += f"Stack: {', '.join(str(s) for s in stack[:5])}\n\n"
        else:
            suggested_content += "<!-- Describe your project's stack -->\n\n"

        suggested_content += "## Code Conventions\n\n<!-- Document your coding standards -->\n\n"
        suggested_content += "## Common Commands\n\n<!-- List build/test/lint commands -->\n\n"
        suggested_content += "## Architecture Notes\n\n<!-- Describe key patterns -->\n\n"
        suggested_content += "## Forbidden Patterns\n\n<!-- List things to avoid -->\n\n"

        return {
            "title": "AGENTS.md",
            "sections": sections,
            "suggested_content": suggested_content,
            "stack": stack[:10] if stack else [],
            "tools_detected": tools_detected[:5] if tools_detected else [],
        }
    except Exception:
        return {
            "title": "AGENTS.md",
            "sections": [],
            "suggested_content": "# AGENTS.md\n\n<!-- Add project documentation for AI tools -->\n",
        }


def _detect_architecture_from_normalized(norm: dict[str, Any], scan_results: dict[str, Any]) -> list[Recommendation]:
    """Derive architecture memory recommendations from normalized scan signals."""
    recs: list[Recommendation] = []
    if not norm:
        return recs

    project_count = norm.get("projectCount", 0)
    ai_usage_span_days = norm.get("aiUsageSpanDays", 0)
    config_files = scan_results.get("config_files", [])

    # Check if architecture docs exist
    has_agents = any("agents" in str(f).lower() for f in config_files) if config_files else False
    has_architecture = any("architecture" in str(f).lower() for f in config_files) if config_files else False

    # projectCount > 5 AND no AGENTS.md detected -> recommend
    if project_count > 5 and not has_agents:
        recs.append(Recommendation(
            category="skills",
            headline=f"{project_count} projects without AGENTS.md — document your architecture for AI tools",
            detail=(
                f"You work across {project_count} projects but have no AGENTS.md detected. "
                f"AGENTS.md tells AI tools about your conventions, architecture, and preferences "
                f"so they don't have to guess or ask."
            ),
            action_type="generate_agents_md",
            trust_level="heuristic",
            confidence=63,
            evidence=f"{project_count} projects, no AGENTS.md (normalized scan data)",
            priority="medium",
            teach_text=(
                "AGENTS.md is a project-level instruction file that AI coding tools read "
                "automatically. It documents: project structure, conventions, common commands, "
                "and things the AI should know."
            ),
            auto_action="Generate AGENTS.md template based on project scan",
        ))

    # aiUsageSpanDays > 30 AND no architecture docs -> recommend
    if ai_usage_span_days > 30 and not has_architecture:
        recs.append(Recommendation(
            category="skills",
            headline=f"{ai_usage_span_days} days of AI usage without architecture docs — generate ARCHITECTURE.md",
            detail=(
                f"You've been using AI tools for {ai_usage_span_days} days but have no "
                f"architecture documentation. An ARCHITECTURE.md helps AI tools understand "
                f"your codebase structure without re-explaining it each session."
            ),
            action_type="generate_architecture_doc",
            trust_level="heuristic",
            confidence=60,
            evidence=f"{ai_usage_span_days} days span, no architecture docs (normalized)",
            priority="low",
            teach_text=(
                "ARCHITECTURE.md documents your codebase's high-level structure: "
                "modules, layers, key abstractions, and boundaries."
            ),
            auto_action="Generate ARCHITECTURE.md based on project scan results",
        ))

    return recs


def detect(
    sessions: list[Any], profile: dict[str, Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Run all architecture memory detectors."""
    recs: list[Recommendation] = []
    try:
        # Session-based detection
        if sessions:
            recs.extend(_detect_architecture_doc_need(sessions, scan_results))
            recs.extend(_detect_agents_md_need(sessions, scan_results))
            recs.extend(_detect_gemini_md_need(sessions, scan_results))

        # Normalized-signal detection
        norm = scan_results.get("normalized", {}) if scan_results else {}
        if norm:
            recs.extend(_detect_architecture_from_normalized(norm, scan_results))
    except Exception:
        pass
    return recs


def _detect_gemini_md_need(
    sessions: list[Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Recommend GEMINI.md when Google/Gemini tools are detected in sessions.

    Checks for Gemini model usage, Google AI Studio references, or
    Gemini-specific patterns in session data.
    """
    recs: list[Recommendation] = []
    if not sessions:
        return recs

    # Check if GEMINI.md already exists
    config_files = scan_results.get("config_files", [])
    for f in config_files:
        f_lower = str(f).lower() if f else ""
        if "gemini.md" in f_lower or "gemini" in f_lower and f_lower.endswith(".md"):
            return recs

    # Detect Gemini/Google AI usage
    gemini_signals = 0
    evidence_parts: list[str] = []

    # Check models used
    models = scan_results.get("models", [])
    for m in models:
        m_lower = str(m).lower() if m else ""
        if "gemini" in m_lower or "google" in m_lower:
            gemini_signals += 1
            evidence_parts.append(f"model: {m}")

    # Check tools detected
    tools = scan_results.get("tools_detected", [])
    for t in tools:
        t_lower = str(t).lower() if t else ""
        if "gemini" in t_lower or "google" in t_lower or "aistudio" in t_lower:
            gemini_signals += 1
            evidence_parts.append(f"tool: {t}")

    # Check session models
    for s in sessions:
        if isinstance(s, dict):
            model = s.get("model", "")
        else:
            model = getattr(s, "model", "") or ""
        if model and ("gemini" in model.lower() or "google" in model.lower()):
            gemini_signals += 1
            if f"session model: {model}" not in evidence_parts:
                evidence_parts.append(f"session model: {model}")
            break  # one signal is enough from sessions

    if gemini_signals < 1:
        return recs

    recs.append(Recommendation(
        category="architecture_memory",
        headline="Gemini/Google AI usage detected — generate GEMINI.md for project context",
        detail=(
            f"Detected Google/Gemini AI usage ({'; '.join(evidence_parts[:3])}). "
            f"A GEMINI.md file provides project-specific context and instructions "
            f"for Gemini-based tools, similar to CLAUDE.md for Claude."
        ),
        action_type="generate_gemini_md",
        trust_level="heuristic",
        confidence=68,
        evidence="; ".join(evidence_parts[:3]),
        priority="low",
        teach_text=(
            "GEMINI.md is a project context file for Google's Gemini AI tools. "
            "It tells Gemini about your project structure, conventions, and preferences — "
            "similar to how CLAUDE.md works for Claude or .cursorrules for Cursor."
        ),
        auto_action="Generate GEMINI.md from project scan results",
    ))

    return recs


def generate_gemini_md(scan_results: dict[str, Any]) -> dict[str, str]:
    """Generate Gemini AI config markdown from scan results.

    Args:
        scan_results: Project scan results dict.

    Returns:
        Dict with 'filename' and 'content' (markdown Gemini config).
    """
    try:
        sections: list[str] = ["# GEMINI.md\n"]
        sections.append("Project configuration for Google Gemini AI tools.\n")

        # Project overview from scan
        summary = scan_results.get("summary", "")
        if summary:
            sections.append("## Project Overview\n")
            sections.append(f"{summary}\n")

        # Stack
        stack = scan_results.get("stack", [])
        if stack:
            sections.append("## Tech Stack\n")
            for item in stack[:10]:
                sections.append(f"- {item}")
            sections.append("")

        # Project structure
        projects = scan_results.get("projects", [])
        if projects:
            sections.append("## Projects\n")
            for proj in projects[:5]:
                if isinstance(proj, dict):
                    sections.append(f"- {proj.get('name', proj.get('path', 'unknown'))}")
                else:
                    sections.append(f"- {proj}")
            sections.append("")

        # AI tools context
        tools = scan_results.get("tools_detected", [])
        if tools:
            sections.append("## AI Tools in Use\n")
            for tool in tools[:10]:
                sections.append(f"- {tool}")
            sections.append("")

        # Conventions
        sections.append("## Conventions\n")
        sections.append("- Follow existing code style and patterns")
        sections.append("- Write tests for new functionality")
        sections.append("- Keep changes focused and atomic")
        sections.append("- Document public interfaces\n")

        content = "\n".join(sections)
        return {
            "filename": "GEMINI.md",
            "content": content,
        }
    except Exception:
        return {
            "filename": "GEMINI.md",
            "content": "# GEMINI.md\n\n<!-- Add Gemini AI configuration here -->\n",
        }
