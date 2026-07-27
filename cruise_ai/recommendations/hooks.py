"""cruise_ai.recommendations.hooks — detect opportunities for automation hooks.

Provides:
- Repetitive Command Detection: find command sequences repeated across sessions
- Hook Recommendation: suggest git hooks or build hooks for common patterns
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from cruise_ai.recommendations.types import Recommendation

# Known hook-able command patterns
GIT_HOOK_PATTERNS = [
    (["git add", "git commit"], "pre-commit"),
    (["git commit", "git push"], "pre-push"),
    (["git pull", "git rebase"], "post-merge"),
]

BUILD_HOOK_PATTERNS = [
    (["test", "lint"], "build"),
    (["lint", "format"], "pre-commit"),
    (["build", "deploy"], "post-build"),
    (["typecheck", "test"], "build"),
    (["pytest", "mypy"], "build"),
    (["npm test", "npm run lint"], "build"),
    (["jest", "eslint"], "build"),
]


def _extract_command_sequences(sessions: list[Any]) -> list[list[str]]:
    """Extract command lists from sessions."""
    all_sequences: list[list[str]] = []

    for s in sessions:
        commands = getattr(s, "commands", None)
        if commands is None:
            if isinstance(s, dict):
                commands = s.get("commands", [])
            else:
                commands = []
        if commands:
            all_sequences.append([str(c).lower().strip() for c in commands if c])

    return all_sequences


def _normalize_command(cmd: str) -> str:
    """Normalize a command to its base form for pattern matching."""
    cmd = cmd.strip().lower()
    # Strip common prefixes
    for prefix in ["sudo ", "npx ", "bunx ", "pnpm ", "yarn "]:
        if cmd.startswith(prefix):
            cmd = cmd[len(prefix):]
    # Get base command
    parts = cmd.split()
    if not parts:
        return ""
    # Return first 2 parts for git commands, first part otherwise
    if parts[0] == "git" and len(parts) > 1:
        return f"git {parts[1]}"
    return parts[0]


def _detect_repetitive_commands(sessions: list[Any]) -> list[Recommendation]:
    """Detect command patterns repeated across sessions."""
    recs: list[Recommendation] = []
    if len(sessions) < 5:
        return recs

    sequences = _extract_command_sequences(sessions)
    if not sequences:
        return recs

    # Count normalized command pairs (bigrams)
    pair_counts: Counter[tuple[str, str]] = Counter()
    for seq in sequences:
        normalized = [_normalize_command(c) for c in seq if _normalize_command(c)]
        for i in range(len(normalized) - 1):
            pair = (normalized[i], normalized[i + 1])
            pair_counts[pair] += 1

    # Find pairs appearing in >5 sessions
    frequent_pairs = [(pair, count) for pair, count in pair_counts.items() if count > 5]
    if not frequent_pairs:
        return recs

    frequent_pairs.sort(key=lambda x: -x[1])

    for (cmd1, cmd2), count in frequent_pairs[:3]:
        # Determine hook type
        is_git_hook = cmd1.startswith("git") or cmd2.startswith("git")
        action_type = "create_git_hook" if is_git_hook else "create_build_hook"
        hook_type = "git hook" if is_git_hook else "build hook"

        # Determine specific hook stage
        hook_stage = "pre-commit"
        if is_git_hook:
            for pattern_cmds, stage in GIT_HOOK_PATTERNS:
                if any(p in cmd1 for p in pattern_cmds) or any(p in cmd2 for p in pattern_cmds):
                    hook_stage = stage
                    break
        else:
            for pattern_cmds, stage in BUILD_HOOK_PATTERNS:
                if any(p in cmd1 for p in pattern_cmds) or any(p in cmd2 for p in pattern_cmds):
                    hook_stage = stage
                    break

        recs.append(Recommendation(
            category="hooks",
            headline=f"'{cmd1}' → '{cmd2}' repeated {count} times — automate with a {hook_type}",
            detail=(
                f"The command sequence '{cmd1}' followed by '{cmd2}' appears {count} times "
                f"across your sessions. A {hook_stage} hook would run this automatically, "
                f"saving you from manually executing it every time."
            ),
            action_type=action_type,
            trust_level="observed",
            confidence=min(85, 65 + count),
            evidence=f"'{cmd1}' → '{cmd2}' appears {count} times in {len(sessions)} sessions",
            priority="medium" if count < 10 else "high",
            teach_text=(
                f"A {hook_type} runs commands automatically at specific points in your workflow. "
                f"For example, a pre-commit hook runs tests before every commit, catching "
                f"issues before they enter version control. Benefits:\n"
                f"- Never forget to run '{cmd2}' after '{cmd1}'\n"
                f"- Consistent quality gates across all team members\n"
                f"- Saves ~{count * 5} seconds of manual execution per iteration"
            ),
            auto_action=f"Generate a {hook_stage} hook that runs '{cmd1}' then '{cmd2}'",
            savings_estimate={"executions_saved": count, "seconds_per_execution": 5},
        ))
        break  # Only report top pattern to avoid noise

    return recs


def _detect_single_command_repetition(sessions: list[Any]) -> list[Recommendation]:
    """Detect single commands repeated excessively across sessions."""
    recs: list[Recommendation] = []
    if len(sessions) < 5:
        return recs

    command_session_counts: Counter[str] = Counter()
    for s in sessions:
        commands = getattr(s, "commands", None)
        if commands is None:
            if isinstance(s, dict):
                commands = s.get("commands", [])
            else:
                commands = []
        seen: set[str] = set()
        for cmd in commands:
            normalized = _normalize_command(str(cmd))
            if normalized and normalized not in seen:
                command_session_counts[normalized] += 1
                seen.add(normalized)

    # Commands appearing in almost every session
    total_sessions = len(sessions)
    for cmd, count in command_session_counts.most_common(5):
        if count > 5 and count / total_sessions > 0.6:
            # Skip very basic commands
            if cmd in {"cd", "ls", "cat", "echo", "pwd"}:
                continue
            is_git = cmd.startswith("git")
            action_type = "create_git_hook" if is_git else "create_build_hook"

            recs.append(Recommendation(
                category="hooks",
                headline=f"'{cmd}' runs in {count}/{total_sessions} sessions — consider automating",
                detail=(
                    f"The command '{cmd}' appears in {count} of {total_sessions} sessions "
                    f"({count/total_sessions*100:.0f}%). If this is part of your standard "
                    f"workflow, a hook or alias would save repetitive typing."
                ),
                action_type=action_type,
                trust_level="observed",
                confidence=68,
                evidence=f"'{cmd}' in {count}/{total_sessions} sessions ({count/total_sessions*100:.0f}%)",
                priority="low",
                teach_text=(
                    "Commands you run in almost every session are prime candidates for "
                    "automation. Options include:\n"
                    "- Git hooks (run automatically at git events)\n"
                    "- Shell aliases (shorter to type)\n"
                    "- Task runners (npm scripts, Makefile targets)\n"
                    "- IDE run configurations"
                ),
                auto_action=f"Create automation for '{cmd}' based on when it's typically run",
            ))
            break  # Only top one

    return recs


def generate_git_hook(hook_type: str, commands: list[str]) -> dict[str, str]:
    """Generate a git hook shell script.

    Args:
        hook_type: One of 'pre-commit', 'post-commit', 'pre-push'.
        commands: List of commands to run in the hook.

    Returns:
        Dict with 'filename', 'content' (shell script), 'description'.
    """
    try:
        valid_types = {"pre-commit", "post-commit", "pre-push"}
        if hook_type not in valid_types:
            hook_type = "pre-commit"

        cmd_block = ""
        for cmd in commands:
            cmd_block += (
                f'echo "Running: {cmd}"\n'
                f'if ! {cmd}; then\n'
                f'    echo "FAILED: {cmd}"\n'
                f'    exit 1\n'
                f'fi\n\n'
            )

        content = (
            f'#!/bin/sh\n'
            f'# Auto-generated {hook_type} hook\n'
            f'# Generated by cruise-ai recommendation engine\n'
            f'\n'
            f'set -e\n'
            f'\n'
            f'{cmd_block}'
            f'echo "All {hook_type} checks passed."\n'
            f'exit 0\n'
        )

        return {
            "filename": f".git/hooks/{hook_type}",
            "content": content,
            "description": f"Git {hook_type} hook running {len(commands)} command(s)",
        }
    except Exception:
        return {
            "filename": f".git/hooks/{hook_type}",
            "content": "",
            "description": "Failed to generate git hook",
        }


def generate_build_hook(commands: list[str]) -> dict[str, str]:
    """Generate a CI/build automation script.

    Args:
        commands: List of build/test commands to automate.

    Returns:
        Dict with 'filename', 'content' (shell script), 'description'.
    """
    try:
        cmd_block = ""
        for cmd in commands:
            cmd_block += (
                f'echo "Step: {cmd}"\n'
                f'if ! {cmd}; then\n'
                f'    echo "BUILD FAILED at: {cmd}"\n'
                f'    exit 1\n'
                f'fi\n\n'
            )

        content = (
            f'#!/bin/sh\n'
            f'# Auto-generated build automation script\n'
            f'# Generated by cruise-ai recommendation engine\n'
            f'\n'
            f'set -e\n'
            f'\n'
            f'echo "=== Build Pipeline ==="\n'
            f'\n'
            f'{cmd_block}'
            f'echo "=== Build Complete ==="\n'
            f'exit 0\n'
        )

        return {
            "filename": "scripts/build.sh",
            "content": content,
            "description": f"Build automation script with {len(commands)} step(s)",
        }
    except Exception:
        return {
            "filename": "scripts/build.sh",
            "content": "",
            "description": "Failed to generate build hook",
        }


def generate_pr_hook(checks: list[str]) -> dict[str, str]:
    """Generate a GitHub Actions workflow YAML for PR checks.

    Args:
        checks: List of commands/checks to run on PRs.

    Returns:
        Dict with 'filename', 'content' (YAML workflow), 'description'.
    """
    try:
        steps = "      - uses: actions/checkout@v4\n"
        for check in checks:
            step_name = check.replace('"', '\\"').split()[0] if check else "check"
            steps += (
                f'      - name: {step_name}\n'
                f'        run: {check}\n'
            )

        content = (
            f'name: PR Checks\n'
            f'\n'
            f'on:\n'
            f'  pull_request:\n'
            f'    branches: [main]\n'
            f'\n'
            f'jobs:\n'
            f'  check:\n'
            f'    runs-on: ubuntu-latest\n'
            f'    steps:\n'
            f'{steps}'
        )

        return {
            "filename": ".github/workflows/pr-checks.yml",
            "content": content,
            "description": f"GitHub Actions PR workflow with {len(checks)} check(s)",
        }
    except Exception:
        return {
            "filename": ".github/workflows/pr-checks.yml",
            "content": "",
            "description": "Failed to generate PR hook",
        }


def detect(
    sessions: list[Any], profile: dict[str, Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Run all hook detectors.

    Checks for repetitive command patterns in sessions and recommends
    git hooks or build hooks to automate them.
    """
    recs: list[Recommendation] = []

    try:
        recs.extend(_detect_repetitive_commands(sessions))
        recs.extend(_detect_single_command_repetition(sessions))
    except Exception:
        return []

    return recs
