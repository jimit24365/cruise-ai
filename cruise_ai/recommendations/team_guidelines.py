"""cruise_ai.recommendations.team_guidelines — detect and generate team coding guidelines.

Provides:
- detect: recommend generating team guidelines when consistent patterns are found
- generate_team_guidelines: produce markdown team coding rules
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from cruise_ai.recommendations.types import Recommendation

# Known linter/formatter patterns
_LINTER_PATTERNS = [
    "eslint", "prettier", "black", "ruff", "flake8", "pylint",
    "rubocop", "golint", "clippy", "stylelint", "biome",
]

# Known test framework patterns
_TEST_FRAMEWORK_PATTERNS = [
    "pytest", "jest", "mocha", "vitest", "rspec", "junit",
    "go test", "cargo test", "playwright", "cypress",
]

# Known commit style patterns
_COMMIT_PATTERNS = [
    "conventional", "commitlint", "husky", "pre-commit",
    "commitizen", "semantic-release", "angular commit",
]


def _extract_patterns(sessions: list[Any], scan_results: dict[str, Any]) -> dict[str, list[str]]:
    """Extract consistent coding patterns from sessions and scan results.

    Returns dict with keys: linters, test_frameworks, commit_styles, other.
    """
    detected: dict[str, list[str]] = {
        "linters": [],
        "test_frameworks": [],
        "commit_styles": [],
        "other": [],
    }

    # Collect all commands and config files
    all_commands: list[str] = []
    for s in sessions:
        if isinstance(s, dict):
            commands = s.get("commands", [])
        else:
            commands = getattr(s, "commands", []) or []
        for cmd in commands:
            if isinstance(cmd, str):
                all_commands.append(cmd.lower())

    combined = " ".join(all_commands)

    # Also check config files from scan_results
    config_files = scan_results.get("config_files", [])
    config_text = " ".join(str(f).lower() for f in config_files if f)

    search_text = combined + " " + config_text

    # Detect linters
    for pattern in _LINTER_PATTERNS:
        if pattern in search_text:
            detected["linters"].append(pattern)

    # Detect test frameworks
    for pattern in _TEST_FRAMEWORK_PATTERNS:
        if pattern in search_text:
            detected["test_frameworks"].append(pattern)

    # Detect commit styles
    for pattern in _COMMIT_PATTERNS:
        if pattern in search_text:
            detected["commit_styles"].append(pattern)

    # Check stack from scan_results
    stack = scan_results.get("stack", [])
    for item in stack:
        item_lower = str(item).lower() if item else ""
        for pattern in _LINTER_PATTERNS:
            if pattern in item_lower and pattern not in detected["linters"]:
                detected["linters"].append(pattern)
        for pattern in _TEST_FRAMEWORK_PATTERNS:
            if pattern in item_lower and pattern not in detected["test_frameworks"]:
                detected["test_frameworks"].append(pattern)

    return detected


def generate_team_guidelines(patterns: dict[str, list[str]]) -> dict[str, str]:
    """Generate markdown team coding guidelines from detected patterns.

    Args:
        patterns: Dict with linters, test_frameworks, commit_styles, other lists.

    Returns:
        Dict with 'filename' and 'content' (markdown team coding rules).
    """
    try:
        sections: list[str] = ["# Team Coding Guidelines\n"]
        sections.append("_Auto-generated from detected project patterns._\n")

        # Linting & Formatting
        linters = patterns.get("linters", [])
        if linters:
            sections.append("## Linting & Formatting\n")
            for linter in linters:
                sections.append(f"- **{linter}**: Enabled and enforced")
            sections.append("")
            sections.append("All code must pass linting before commit. "
                          "Run the linter before pushing.\n")

        # Testing
        test_frameworks = patterns.get("test_frameworks", [])
        if test_frameworks:
            sections.append("## Testing\n")
            sections.append(f"- Framework(s): {', '.join(test_frameworks)}")
            sections.append("- All new features must include tests")
            sections.append("- Tests must pass before merge")
            sections.append("- Aim for meaningful coverage, not 100% line coverage\n")

        # Commit Style
        commit_styles = patterns.get("commit_styles", [])
        if commit_styles:
            sections.append("## Commit Style\n")
            sections.append(f"- Convention: {', '.join(commit_styles)}")
            sections.append("- Use conventional commit format: `type(scope): description`")
            sections.append("- Types: feat, fix, docs, style, refactor, test, chore\n")

        # General Rules
        sections.append("## General Rules\n")
        sections.append("- Keep PRs focused — one concern per PR")
        sections.append("- Write self-documenting code; add comments for WHY, not WHAT")
        sections.append("- Review your own PR before requesting review")
        sections.append("- Update documentation when changing public interfaces\n")

        content = "\n".join(sections)
        return {
            "filename": "TEAM-GUIDELINES.md",
            "content": content,
        }
    except Exception:
        return {
            "filename": "TEAM-GUIDELINES.md",
            "content": "# Team Coding Guidelines\n\n<!-- Add your team's coding rules here -->\n",
        }


def _detect_guidelines_from_normalized(norm: dict[str, Any], scan_results: dict[str, Any]) -> list[Recommendation]:
    """Derive team guidelines recommendations from normalized scan signals."""
    recs: list[Recommendation] = []
    if not norm:
        return recs

    project_count = norm.get("projectCount", 0)
    longest_streak_days = norm.get("longestStreakDays", 0)

    # Check if team guidelines already exist
    config_files = scan_results.get("config_files", [])
    for f in config_files:
        f_lower = str(f).lower() if f else ""
        if "team-guide" in f_lower or "team_guide" in f_lower or "contributing" in f_lower:
            return recs

    # projectCount > 5 AND longestStreakDays > 14 -> recommend team guidelines
    if project_count > 5 and longest_streak_days > 14:
        recs.append(Recommendation(
            category="skills",
            headline=f"{project_count} projects over {longest_streak_days}-day streak — document team guidelines",
            detail=(
                f"With {project_count} projects and a {longest_streak_days}-day active streak, "
                f"you have established patterns worth documenting. Team guidelines codify "
                f"your conventions so AI tools (and team members) follow them consistently."
            ),
            action_type="generate_team_guidelines",
            trust_level="heuristic",
            confidence=60,
            evidence=f"{project_count} projects, {longest_streak_days}-day streak (normalized)",
            priority="low",
            teach_text=(
                "Team guidelines document your project's conventions: which linter to use, "
                "how to write tests, what commit style to follow. They help both human "
                "developers and AI tools understand your standards."
            ),
            auto_action="Generate TEAM-GUIDELINES.md from detected patterns",
        ))

    return recs


def detect(
    sessions: list[Any], profile: dict[str, Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Recommend generating team guidelines when consistent patterns are detected.

    Triggers when sessions show consistent use of same linter, test framework,
    or commit style across multiple sessions.
    """
    recs: list[Recommendation] = []
    try:
        # Session-based detection
        if sessions and len(sessions) >= 5:
            patterns = _extract_patterns(sessions, scan_results)

            # Count how many categories have consistent patterns
            categories_with_patterns = sum(
                1 for v in patterns.values() if len(v) >= 1
            )

            if categories_with_patterns >= 2:
                # Build evidence
                evidence_parts: list[str] = []
                if patterns["linters"]:
                    evidence_parts.append(f"linters: {', '.join(patterns['linters'][:3])}")
                if patterns["test_frameworks"]:
                    evidence_parts.append(f"tests: {', '.join(patterns['test_frameworks'][:3])}")
                if patterns["commit_styles"]:
                    evidence_parts.append(f"commits: {', '.join(patterns['commit_styles'][:3])}")

                # Check if team guidelines already exist
                config_files = scan_results.get("config_files", [])
                has_guidelines = False
                for f in config_files:
                    f_lower = str(f).lower() if f else ""
                    if "team-guide" in f_lower or "team_guide" in f_lower or "contributing" in f_lower:
                        has_guidelines = True
                        break

                if not has_guidelines:
                    recs.append(Recommendation(
                        category="skills",
                        headline="Consistent coding patterns detected — generate team guidelines",
                        detail=(
                            f"Your sessions show consistent use of: {'; '.join(evidence_parts)}. "
                            f"Generating a TEAM-GUIDELINES.md would codify these patterns "
                            f"and help onboard new team members or AI tools."
                        ),
                        action_type="generate_team_guidelines",
                        trust_level="heuristic",
                        confidence=65,
                        evidence="; ".join(evidence_parts),
                        priority="low",
                        teach_text=(
                            "Team guidelines document your project's conventions: which linter to use, "
                            "how to write tests, what commit style to follow. They help both human "
                            "developers and AI tools understand your project's standards without "
                            "having to ask or guess."
                        ),
                        auto_action="Generate TEAM-GUIDELINES.md from detected patterns",
                        savings_estimate={"patterns_detected": categories_with_patterns},
                    ))

        # Normalized-signal detection
        norm = scan_results.get("normalized", {}) if scan_results else {}
        if norm:
            recs.extend(_detect_guidelines_from_normalized(norm, scan_results))
    except Exception:
        pass

    return recs
