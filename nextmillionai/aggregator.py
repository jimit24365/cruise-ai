"""
nextmillionai.aggregator -- Compute normalized metrics from Session objects.

Two public functions:
  - compute_normalized_from_sessions(): aggregate sessions into NormalizedMetrics
  - build_signal_matrix(): group sessions by (project_path, tool) for per-project signals
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from nextmillionai.adapters._base import Session
from nextmillionai.paths import cli_invocation
from nextmillionai.scanner import (
    HOME,
    count_mcp_servers,
    days_between,
)

# Matches "YYYY-MM-DD" at the start of an ISO date string.
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")

# Git date formats: "Wed May 13 22:44:51 2026 +0530"
_GIT_DATE_FMTS = (
    "%a %b %d %H:%M:%S %Y %z",
    "%a %b %d %H:%M:%S %Y",
)


def _parse_day_key(date_str: str) -> str | None:
    """Extract ``YYYY-MM-DD`` from an ISO or git-format date string.

    Returns ``None`` if the string cannot be parsed.
    """
    # Fast path: ISO format "2024-06-01T..."
    m = _ISO_DATE_RE.match(date_str)
    if m:
        return m.group(0)
    # Try git date formats
    for fmt in _GIT_DATE_FMTS:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# Strings that should be treated as "unknown" rather than real model names.
# Placeholders that are not a real model the user chose. "default"/"auto" are
# what Cursor records when no specific model is pinned (its auto-select), so they
# must never masquerade as the go-to model.
_SYNTHETIC_MODELS = frozenset({"<synthetic>", "synthetic", "", "default", "auto"})


def _clean_model(raw: str | None) -> str:
    """Normalize a model string: strip whitespace, replace junk with 'unknown'."""
    if not raw:
        return "unknown"
    label = raw.strip()
    if not label or label.lower() in _SYNTHETIC_MODELS:
        return "unknown"
    return label


def _pick_primary_model(counts: dict) -> str | None:
    """Most-used model — but never the 'unknown' placeholder when a named model
    exists, so Cursor's default/auto usage doesn't win 'go-to model'."""
    if not counts:
        return None
    named = {m: c for m, c in counts.items() if m not in ("unknown", "cursor (auto-select)")}
    pool = named or counts
    return str(max(pool, key=lambda k: pool[k]))


def compute_normalized_from_sessions(
    sessions: list[Session],
    raw_data: dict[str, dict | None],
    git_data: dict | None,
) -> dict:
    """Aggregate Session objects into NormalizedMetrics.

    Session-derived metrics (totalSessions, avgTurnsPerTask, maxParallelAgents, etc.)
    come from the sessions list.  Tool-specific metrics (aiLineSurvivalRate,
    composerRatio) come from raw_data["cursor"] for now.
    """
    n: dict[str, Any] = {}

    # ── Pull out tool-specific raw data ──
    claude_data = raw_data.get("claude_code")
    cursor_data = raw_data.get("cursor")
    codex_data = raw_data.get("codex")

    # ── Aggregate counts from sessions ──
    total_sessions = len(sessions)
    total_user_msgs = sum(s.user_msgs for s in sessions)
    sum(s.assistant_msgs for s in sessions)

    # Models
    all_models: set[str] = set()
    for s in sessions:
        all_models.update(s.models)

    # Timestamps
    earliest_global: datetime | None = None
    latest_global: datetime | None = None
    for s in sessions:
        if s.started_at:
            if earliest_global is None or s.started_at < earliest_global:
                earliest_global = s.started_at
        if s.ended_at:
            if latest_global is None or s.ended_at > latest_global:
                latest_global = s.ended_at

    earliest_iso = earliest_global.isoformat() if earliest_global else None
    latest_iso = latest_global.isoformat() if latest_global else None

    # ── Legacy counts from raw data (for backward compat with cursor-specific metrics) ──
    total_scored_commits = 0
    total_ai_code_blocks = 0
    total_plans = 0
    total_conversations = 0

    cursor_ai = None
    cursor_commits = None
    cursor_convos = None
    cursor_plans_data = None

    if cursor_data:
        cursor_ai = cursor_data.get("ai_code")
        cursor_commits = cursor_data.get("scored_commits")
        cursor_convos = cursor_data.get("conversations")
        cursor_plans_data = cursor_data.get("plans")
        cursor_data.get("transcripts")

        if cursor_ai:
            total_ai_code_blocks += cursor_ai.get("totalHashes", 0)
        if cursor_commits:
            total_scored_commits += cursor_commits.get("totalCommits", 0)
        if cursor_convos:
            total_conversations += cursor_convos.get("totalConversations", 0)
        if cursor_plans_data:
            total_plans += cursor_plans_data.get("totalPlans", 0)

    # Project count from git
    project_count = 0
    all_languages: set[str] = set()
    if git_data and git_data.get("projects"):
        project_count = len(git_data["projects"])
        for p in git_data["projects"]:
            for lang in p.get("languages", []):
                all_languages.add(lang)

    # AI usage span
    ai_usage_span_days = days_between(earliest_iso, latest_iso) or 0

    # ── Populate normalized metrics ──

    n["totalSessions"] = total_sessions
    n["totalScoredCommits"] = total_scored_commits
    n["totalAiCodeBlocks"] = total_ai_code_blocks
    n["projectCount"] = project_count
    n["aiUsageSpanDays"] = ai_usage_span_days
    n["modelCount"] = len(all_models)
    n["planCount"] = total_plans
    n["languageCount"] = len(all_languages)

    # ── Cursor-derived metrics (exact from DB) ──

    if cursor_commits and cursor_commits.get("totalCommits", 0) > 0:
        total_ai = cursor_commits.get("totalAiLines", 0)
        total_human = cursor_commits.get("totalHumanLines", 0)
        total_added = cursor_commits.get("totalLinesAdded", 0)
        total_composer = cursor_commits.get("totalComposerLines", 0)

        avg_pct = cursor_commits.get("avgAiPercentage")
        if avg_pct is not None:
            n["aiLineSurvivalRate"] = round(min(avg_pct / 100.0, 1.0), 3)

        if total_human > 0:
            n["leverageRatio"] = round(total_ai / total_human, 1)
        elif total_ai > 0:
            n["leverageRatio"] = float(total_ai)

        if total_ai > 0:
            n["composerRatio"] = round(total_composer / total_ai, 3)

        if total_added > 0:
            n["postAiEditRate"] = round(total_human / total_added, 3)

    # ── Conversation/mode metrics from Cursor ──

    if cursor_convos:
        modes = cursor_convos.get("modes", {})
        total_mode_count = sum(modes.values()) if modes else 0
        if total_mode_count > 0:
            agent_count = modes.get("agent", 0) + modes.get("agentic", 0)
            n["agentModeRatio"] = round(agent_count / total_mode_count, 3)

    # ── Plan complexity ──

    if cursor_plans_data and cursor_plans_data.get("plans"):
        plan_lines = [p["lineCount"] for p in cursor_plans_data["plans"] if "lineCount" in p]
        if plan_lines:
            n["avgPlanComplexity"] = round(sum(plan_lines) / len(plan_lines), 1)

    # ── Session-derived metrics (from all tools) ──

    # avgTurnsPerTask
    if total_sessions > 0 and total_user_msgs > 0:
        n["avgTurnsPerTask"] = round(total_user_msgs / total_sessions, 1)

    # filesPerSession
    total_file_tools = sum(s.tool_calls_by_type.get("file", 0) for s in sessions)
    if total_sessions > 0:
        n["filesPerSession"] = round(total_file_tools / total_sessions, 1)

    # terminalCommandCount
    n["terminalCommandCount"] = sum(s.tool_calls_by_type.get("terminal", 0) for s in sessions)

    # avgPromptWords
    total_words = sum(sum(s.prompt_word_counts) for s in sessions)
    if total_user_msgs > 0:
        n["avgPromptWords"] = round(total_words / total_user_msgs)

    # ── Wrapped signal fields ──

    # peakProductivityHour
    hour_counts: dict[int, int] = {}
    for s in sessions:
        if s.started_at:
            h = s.started_at.hour
            hour_counts[h] = hour_counts.get(h, 0) + 1
    if hour_counts:
        n["peakProductivityHour"] = max(hour_counts, key=hour_counts.get)  # type: ignore[arg-type]
    else:
        n["peakProductivityHour"] = 14

    # longestStreakDays
    session_dates: set[str] = set()
    for s in sessions:
        for dt in (s.started_at, s.ended_at):
            if dt:
                session_dates.add(dt.strftime("%Y-%m-%d"))
    if session_dates:
        sorted_dates = sorted(session_dates)
        max_streak = 1
        current_streak = 1
        for i in range(1, len(sorted_dates)):
            try:
                prev = datetime.strptime(sorted_dates[i - 1], "%Y-%m-%d")
                curr = datetime.strptime(sorted_dates[i], "%Y-%m-%d")
                if (curr - prev).days == 1:
                    current_streak += 1
                    max_streak = max(max_streak, current_streak)
                else:
                    current_streak = 1
            except Exception:
                current_streak = 1
        n["longestStreakDays"] = max_streak
    else:
        n["longestStreakDays"] = 0

    # avgPromptsPerSession
    if total_sessions > 0:
        user_msg_counts = [s.user_msgs for s in sessions]
        if user_msg_counts:
            n["avgPromptsPerSession"] = round(sum(user_msg_counts) / len(user_msg_counts), 1)

    # totalEstimatedHours / longestSessionMinutes
    total_minutes = 0.0
    longest_session_min = 0.0
    for s in sessions:
        if s.started_at and s.ended_at:
            dur_min = max(0, (s.ended_at - s.started_at).total_seconds() / 60.0)
            dur_min = min(dur_min, 480)  # cap at 8 hours
            total_minutes += dur_min
            longest_session_min = max(longest_session_min, dur_min)
    n["totalEstimatedHours"] = round(total_minutes / 60.0, 1) if total_minutes > 0 else 0
    n["longestSessionMinutes"] = round(longest_session_min) if longest_session_min > 0 else 0

    # primaryModel — clean placeholders, and never let "unknown" win the go-to slot
    all_model_counts: dict[str, int] = {}
    for s in sessions:
        for m in s.models:
            label = _clean_model(m)
            all_model_counts[label] = all_model_counts.get(label, 0) + 1
    # Also include cursor-specific model counts
    if cursor_data:
        ai_code = cursor_data.get("ai_code")
        if ai_code and ai_code.get("byModel"):
            for model, cnt in ai_code["byModel"].items():
                label = _clean_model(model)
                all_model_counts[label] = all_model_counts.get(label, 0) + cnt
        convos = cursor_data.get("conversations")
        if convos and convos.get("models"):
            for model, cnt in convos["models"].items():
                label = _clean_model(model)
                all_model_counts[label] = all_model_counts.get(label, 0) + cnt
    primary = _pick_primary_model(all_model_counts)
    if primary:
        n["primaryModel"] = primary

    # ── Tool detection metrics ──

    tools_detected: list[str] = []
    if claude_data:
        tools_detected.append("claude_code")
    if cursor_data:
        tools_detected.append("cursor_ide")
    if codex_data:
        tools_detected.append("codex_cli")

    n["cliAiToolCount"] = len([t for t in tools_detected if t in ("claude_code", "codex_cli")])
    n["uniqueToolCount"] = len(tools_detected) + (1 if total_plans > 0 else 0)

    # ── MCP server detection (all consented clients, deduped by name) ──
    # Count only — normalized stays a counts-only block (no names).
    desktop_data = raw_data.get("claude_desktop")
    mcp_count, _ = count_mcp_servers(
        HOME,
        (git_data or {}).get("projects", []),
        cursor_enabled=raw_data.get("cursor") is not None,
        desktop_servers=(desktop_data or {}).get("mcpServers"),
    )
    n["mcpServerCount"] = mcp_count

    # ── Heuristic metrics ──

    if "aiLineSurvivalRate" in n and "postAiEditRate" in n:
        survival = n["aiLineSurvivalRate"]
        edit_rate = n["postAiEditRate"]
        n["firstShotAcceptRate"] = round(min(survival * (1.0 - edit_rate * 0.5), 1.0), 3)
    elif cursor_commits and cursor_commits.get("avgAiPercentage"):
        n["firstShotAcceptRate"] = round(min(cursor_commits["avgAiPercentage"] / 100.0, 0.95), 3)

    if claude_data and total_plans > 0:
        tool_ratio = claude_data.get("tool_calls", 0) / max(claude_data.get("total_messages", 1), 1)
        plan_boost = min(total_plans / 50.0, 0.3)
        n["referenceUsageRate"] = round(min(tool_ratio * 0.8 + plan_boost, 1.0), 3)
    elif total_plans > 10:
        n["referenceUsageRate"] = round(min(total_plans / 100.0 + 0.3, 0.8), 3)

    if "aiLineSurvivalRate" in n:
        n["errorFixRate"] = round(min(n["aiLineSurvivalRate"] + 0.05, 1.0), 3)

    if "postAiEditRate" in n and total_ai_code_blocks > 0:
        n["errorsPerAiBlock"] = round(n["postAiEditRate"] * 0.15, 3)
    elif total_ai_code_blocks > 0:
        n["errorsPerAiBlock"] = 0.02

    if "errorFixRate" in n:
        n["correctionConvergenceRate"] = round(n["errorFixRate"] * 0.9, 3)

    # Signal density
    if ai_usage_span_days > 30:
        recent_session_count = 0
        now = datetime.now(timezone.utc)
        for s in sessions:
            if s.ended_at and (now - s.ended_at).days <= 30:
                recent_session_count += 1

        total_sess = total_sessions if total_sessions > 0 else 1
        n["recentSignalDensity"] = round(
            min(recent_session_count / max(total_sess * 0.3, 1), 1.0), 2
        )
        n["historicalSignalDensity"] = round(
            min(total_sessions / max(ai_usage_span_days / 7, 1), 1.0), 2
        )
    else:
        n["recentSignalDensity"] = 0.5
        n["historicalSignalDensity"] = 0.5

    n["recentLanguageCount"] = len(all_languages)
    n["historicalLanguageCount"] = len(all_languages)

    # ── v0.2.0 taxonomy signals ──

    # maxParallelAgents
    intervals: list[tuple[datetime, datetime]] = []
    for s in sessions:
        if s.started_at and s.ended_at:
            intervals.append((s.started_at, s.ended_at))
    if intervals:
        events: list[tuple[datetime, int]] = []
        for start, end in intervals:
            events.append((start, 1))
            events.append((end, -1))
        events.sort()
        current_par = 0
        max_par = 0
        for _, delta in events:
            current_par += delta
            max_par = max(max_par, current_par)
        n["maxParallelAgents"] = max_par
    else:
        n["maxParallelAgents"] = 1 if total_sessions > 0 else 0

    # mcpToolCalls
    total_mcp_calls = sum(s.tool_calls_by_type.get("mcp", 0) for s in sessions)
    n["mcpToolCalls"] = total_mcp_calls

    # deepSessionCount
    deep_count = 0
    for s in sessions:
        if s.started_at and s.ended_at:
            if (s.ended_at - s.started_at).total_seconds() >= 1800:
                deep_count += 1
    n["deepSessionCount"] = deep_count

    # fileReadToEditRatio
    total_read_tools = sum(s.tool_calls_by_type.get("read", 0) for s in sessions)
    total_write_tools = sum(s.tool_calls_by_type.get("write", 0) for s in sessions)
    if total_write_tools > 0:
        n["fileReadToEditRatio"] = round(total_read_tools / total_write_tools, 2)
    elif total_read_tools > 0:
        n["fileReadToEditRatio"] = float(total_read_tools)

    # featureToFixRatio
    total_feat = 0
    total_fix = 0
    if git_data and git_data.get("projects"):
        for p in git_data["projects"]:
            total_feat += p.get("feat_commits", 0)
            total_fix += p.get("fix_commits", 0)
    if total_fix > 0:
        n["featureToFixRatio"] = round(total_feat / total_fix, 2)
    elif total_feat > 0:
        n["featureToFixRatio"] = float(total_feat)

    # planModePercent
    if total_sessions > 0 and total_plans > 0:
        n["planModePercent"] = round(total_plans / total_sessions * 100, 1)
    else:
        n["planModePercent"] = 0.0

    return n


def build_signal_matrix(sessions: list[Session]) -> dict:
    """Group sessions by (project_path, tool) into a signal matrix.

    Returns::

        {
            "projects": [
                {
                    "project_path": "/Users/dev/my-app",
                    "project_name": "my-app",
                    "agents": {
                        "claude_code": {
                            "session_count": 5,
                            "total_user_msgs": 120,
                            "total_tool_calls": 340,
                            "models": ["claude-opus-4-6"],
                            "earliest": "...",
                            "latest": "...",
                        },
                        ...
                    },
                },
                ...
            ]
        }
    """
    # Group by project_path
    by_project: dict[str, dict[str, list[Session]]] = {}
    for s in sessions:
        proj = s.project_path or "unknown"
        if proj not in by_project:
            by_project[proj] = {}
        if s.tool not in by_project[proj]:
            by_project[proj][s.tool] = []
        by_project[proj][s.tool].append(s)

    projects = []
    for proj_path, agents in sorted(by_project.items()):
        # Derive project name from path
        parts = proj_path.rstrip("/").split("/")
        proj_name = parts[-1] if parts else proj_path

        agent_data: dict[str, dict] = {}
        for tool, tool_sessions in sorted(agents.items()):
            models: set[str] = set()
            total_user_msgs = 0
            total_tool_calls = 0
            earliest: datetime | None = None
            latest: datetime | None = None

            for s in tool_sessions:
                models.update(s.models)
                total_user_msgs += s.user_msgs
                total_tool_calls += sum(s.tool_calls_by_type.values())
                if s.started_at:
                    if earliest is None or s.started_at < earliest:
                        earliest = s.started_at
                if s.ended_at:
                    if latest is None or s.ended_at > latest:
                        latest = s.ended_at

            agent_data[tool] = {
                "session_count": len(tool_sessions),
                "total_user_msgs": total_user_msgs,
                "total_tool_calls": total_tool_calls,
                "models": sorted(models),
                "earliest": earliest.isoformat() if earliest else None,
                "latest": latest.isoformat() if latest else None,
            }

        projects.append(
            {
                "project_path": proj_path,
                "project_name": proj_name,
                "agents": agent_data,
            }
        )

    return {"projects": projects}


# ── Front-end view builders ─────────────────────────────────────────────────


def build_activity_by_day(
    sessions: list[Session],
    cursor_data: dict | None = None,
    git_data: dict | None = None,
) -> list[dict]:
    """Build per-day activity records from the *union* of all activity sources.

    Sources considered:
    - Sessions (Claude Code, Codex, etc.) — contribute sessions/activeMinutes
    - Cursor scored commits — contribute aiRatio
    - Git commits (from git_data) — contribute known-active dates

    The date range spans the earliest to latest date across *all* sources so
    that, e.g., a Cursor-only day with no Claude session still appears.

    ``aiRatio`` is non-null only for days covered by Cursor scored-commit data
    with a real ``aiPct`` value; all other days resolve to ``None``.
    """
    # Collect per-day data from sessions
    day_data: dict[str, dict] = {}  # date_str -> aggregation bucket

    for s in sessions:
        if not s.started_at:
            continue
        date_str = s.started_at.strftime("%Y-%m-%d")
        if date_str not in day_data:
            day_data[date_str] = {
                "sessions": 0,
                "active_seconds": 0.0,
                "tools": set(),
                "project_counts": {},
            }
        bucket = day_data[date_str]
        bucket["sessions"] += 1
        if s.started_at and s.ended_at:
            dur = max(0, (s.ended_at - s.started_at).total_seconds())
            dur = min(dur, 28800)  # cap at 8 hours
            bucket["active_seconds"] += dur
        bucket["tools"].add(s.tool)
        if s.project_path:
            proj_name = s.project_path.rstrip("/").split("/")[-1]
            bucket["project_counts"][proj_name] = bucket["project_counts"].get(proj_name, 0) + 1

    # Build per-day aiRatio from Cursor scored-commit dates (real data only)
    ai_ratio_by_day: dict[str, float] = {}
    if cursor_data:
        scored = cursor_data.get("scored_commits")
        commit_series = (scored or {}).get("commitDays") or (scored or {}).get("recentCommits", [])
        if commit_series:
            for commit in commit_series:
                cdate = commit.get("date")
                raw_pct = commit.get("aiPct")
                if not cdate or raw_pct is None:
                    continue
                # Coerce aiPct to float (may arrive as string from SQLite)
                try:
                    ai_pct = float(raw_pct)
                except (TypeError, ValueError):
                    continue
                # Parse date — may be ISO ("2024-06-01T...") or git format
                # ("Wed May 13 22:44:51 2026 +0530")
                day_key = _parse_day_key(str(cdate))
                if not day_key:
                    continue
                # Average aiPct for the day if multiple commits
                if day_key not in ai_ratio_by_day:
                    ai_ratio_by_day[day_key] = ai_pct
                else:
                    ai_ratio_by_day[day_key] = (ai_ratio_by_day[day_key] + ai_pct) / 2.0

    # Collect per-day commit counts from git data
    commits_by_day: dict[str, int] = {}
    if git_data and git_data.get("projects"):
        for proj in git_data["projects"]:
            for cdate in proj.get("commit_dates", []):
                dk = _parse_day_key(str(cdate))
                if dk:
                    commits_by_day[dk] = commits_by_day.get(dk, 0) + 1

    # Cursor scored commits also count as commit activity on their day
    if cursor_data:
        scored = cursor_data.get("scored_commits")
        commit_series = (scored or {}).get("commitDays") or (scored or {}).get("recentCommits", [])
        for commit in commit_series:
            dk = _parse_day_key(str(commit.get("date", "")))
            if dk and dk not in commits_by_day:
                commits_by_day[dk] = 1

    # Union of ALL known dates across every source
    all_dates: set[str] = (
        set(day_data.keys()) | set(ai_ratio_by_day.keys()) | set(commits_by_day.keys())
    )
    if not all_dates:
        return []

    sorted_dates = sorted(all_dates)
    try:
        start = datetime.strptime(sorted_dates[0], "%Y-%m-%d")
        end = datetime.strptime(sorted_dates[-1], "%Y-%m-%d")
    except ValueError:
        return []

    # Build output list for every day in the range
    result: list[dict] = []
    current = start
    one_day = __import__("datetime").timedelta(days=1)
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        day_bucket = day_data.get(date_str)
        day_commits = commits_by_day.get(date_str, 0)
        if day_bucket:
            # Find top project
            pc = day_bucket["project_counts"]
            top_project = max(pc, key=pc.get) if pc else None  # type: ignore[arg-type]
            active_min = (
                round(day_bucket["active_seconds"] / 60.0, 1)
                if day_bucket["active_seconds"] > 0
                else None
            )
            tools = set(day_bucket["tools"])
            if day_commits:
                tools.add("git")
            result.append(
                {
                    "date": date_str,
                    "sessions": day_bucket["sessions"],
                    "commits": day_commits,
                    "activeMinutes": active_min,
                    "tools": sorted(tools),
                    "topProject": top_project,
                    "aiRatio": ai_ratio_by_day.get(date_str),
                }
            )
        else:
            result.append(
                {
                    "date": date_str,
                    "sessions": 0,
                    "commits": day_commits,
                    "activeMinutes": None,
                    "tools": ["git"] if day_commits else [],
                    "topProject": None,
                    "aiRatio": ai_ratio_by_day.get(date_str),
                }
            )
        current += one_day

    return result


def build_scanned_projects(
    sessions: list[Session],
    git_data: dict | None = None,
) -> list[dict]:
    """Build project list from real session and git data.

    Returns ``[{name, languages, lastActive, sessionCount}]``.
    Empty list if no projects found.  Never invents data.
    """
    if not sessions and not git_data:
        return []

    # Group sessions by project path
    by_project: dict[str, dict] = {}
    month_counts: dict[str, dict[str, int]] = {}  # path -> {YYYY-MM: n}
    for s in sessions:
        if not s.project_path:
            continue
        path = s.project_path
        if path not in by_project:
            parts = path.rstrip("/").split("/")
            by_project[path] = {
                "name": parts[-1] if parts else path,
                "languages": [],
                "lastActive": None,
                "sessionCount": 0,
            }
        entry = by_project[path]
        entry["sessionCount"] += 1
        if s.started_at:
            mk = s.started_at.strftime("%Y-%m")
            month_counts.setdefault(path, {})[mk] = month_counts.setdefault(path, {}).get(mk, 0) + 1
        for dt in (s.ended_at, s.started_at):
            if dt:
                iso = dt.strftime("%Y-%m-%d")
                if entry["lastActive"] is None or iso > entry["lastActive"]:
                    entry["lastActive"] = iso

    # Per-project monthly activity series (last 12 months with any activity
    # across all projects — shared axis so sparklines compare visually)
    all_months = sorted({m for mc in month_counts.values() for m in mc})[-12:]
    for path, entry in by_project.items():
        mc = month_counts.get(path, {})
        entry["series"] = [mc.get(m, 0) for m in all_months]

    # Enrich with git languages
    if git_data and git_data.get("projects"):
        git_by_path: dict[str, dict] = {p["path"]: p for p in git_data["projects"]}
        for path, entry in by_project.items():
            gp = git_by_path.get(path)
            if gp:
                entry["languages"] = gp.get("languages", [])

        # Add git-only projects (no sessions but scanned)
        for gp in git_data["projects"]:
            if gp["path"] not in by_project:
                by_project[gp["path"]] = {
                    "name": gp.get("name", gp["path"].rstrip("/").split("/")[-1]),
                    "languages": gp.get("languages", []),
                    "lastActive": None,
                    "sessionCount": 0,
                }

    # Sort by session count descending, then name
    result = sorted(
        by_project.values(),
        key=lambda e: (-e["sessionCount"], e["name"]),
    )
    return result


def build_stack_summary(git_data: dict | None) -> dict:
    """Aggregate languages and frameworks from real repo signals.

    Returns ``{languages: {lang: weight}, frameworks: [...]}``.
    Empty if no git data.  Weights sum to 1.0.
    """
    empty: dict = {
        "languages": {},
        "frameworks": [],
        "aiFrameworks": [],
        "databases": [],
        "cloud": [],
    }
    if not git_data or not git_data.get("projects"):
        return empty

    lang_counts: dict[str, int] = {}
    all_frameworks: set[str] = set()
    ai_frameworks: set[str] = set()
    databases: set[str] = set()
    cloud: set[str] = set()

    for p in git_data["projects"]:
        for lang in p.get("languages", []):
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
        for fw in p.get("frameworks", []):
            all_frameworks.add(fw)
        ai_frameworks.update(p.get("aiFrameworks", []))
        databases.update(p.get("databases", []))
        cloud.update(p.get("cloud", []))

    if not lang_counts:
        return empty

    total = sum(lang_counts.values())
    languages = {
        lang: round(count / total, 3)
        for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1])
    }

    return {
        "languages": languages,
        "frameworks": sorted(all_frameworks),
        "aiFrameworks": sorted(ai_frameworks),
        "databases": sorted(databases),
        "cloud": sorted(cloud),
    }


def build_models_summary(
    sessions: list[Session],
    raw_data: dict[str, dict | None],
) -> dict:
    """Build model usage counts from observed model strings.

    Returns ``{byModel: {model: count}, primaryModel: str|None}``.
    Model strings that are empty, placeholders, or ``"<synthetic>"`` are
    labeled ``"unknown"``.
    """
    counts: dict[str, int] = {}

    # From session objects
    for s in sessions:
        for m in s.models:
            label = _clean_model(m)
            counts[label] = counts.get(label, 0) + 1

    # From cursor raw data (has byModel counts).
    # Cursor records "default"/"auto" when no model is pinned — label
    # these "cursor (auto-select)" so the tool usage is visible even
    # though the specific model name isn't recorded.
    cursor_data = raw_data.get("cursor")
    if cursor_data:
        ai_code = cursor_data.get("ai_code")
        if ai_code and ai_code.get("byModel"):
            for model, cnt in ai_code["byModel"].items():
                label = _clean_model(model)
                if label == "unknown":
                    label = "cursor (auto-select)"
                counts[label] = counts.get(label, 0) + cnt
        convos = cursor_data.get("conversations")
        if convos and convos.get("models"):
            for model, cnt in convos["models"].items():
                label = _clean_model(model)
                if label == "unknown":
                    label = "cursor (auto-select)"
                counts[label] = counts.get(label, 0) + cnt

    if not counts:
        return {"byModel": {}, "primaryModel": None}

    # Drop "unknown" from the output — it's an internal sink for
    # null/placeholder model strings, not a real model the user chose.
    visible = {m: c for m, c in counts.items() if m != "unknown"}
    return {
        "byModel": dict(sorted(visible.items(), key=lambda x: -x[1])),
        "primaryModel": _pick_primary_model(counts),
    }


def build_summary_line(
    work_mode: dict | None,
    dimensions: dict | None,
    normalized: dict | None,
) -> str | None:
    """Build a one-liner from scoring output.

    Template: ``"<verb> in <mode> mode — strongest in <dim1> and <dim2>,
    <signature stat>."``

    Returns ``None`` if insufficient data.  Enrichment can override
    this value downstream.
    """
    if not work_mode or not dimensions:
        return None

    dominant = work_mode.get("dominant", {})
    mode_id = dominant.get("id")
    if not mode_id:
        return None

    # Pick verb by mode
    _verbs = {
        "One-Shot-Verify": "Ships",
        "Prompt-Iterate": "Iterates",
        "Architect-First": "Architects",
        "Test-Driven-AI": "Tests",
        "Multi-Agent-Orchestrated": "Orchestrates",
        "Read-Understand-Modify": "Refactors",
        "Hybrid-Manual": "Builds",
        "Exploration-Research": "Explores",
    }
    verb = _verbs.get(mode_id, "Builds")

    # Top 2 scored dimensions
    scored_dims = [
        (dim_id, d["score"])
        for dim_id, d in dimensions.items()
        if isinstance(d, dict) and d.get("score") is not None
    ]
    scored_dims.sort(key=lambda x: x[1], reverse=True)

    if len(scored_dims) < 2:
        return None

    dim_names = {
        "signal_clarity": "Signal Clarity",
        "build_stability": "Build Stability",
        "decision_weight": "Decision Weight",
        "recovery_velocity": "Recovery Velocity",
        "context_command": "Context Command",
        "orchestration_range": "Orchestration Range",
    }

    top1 = dim_names.get(scored_dims[0][0], scored_dims[0][0])
    top2 = dim_names.get(scored_dims[1][0], scored_dims[1][0])

    # Pick one signature stat from normalized metrics
    stat_line = ""
    if normalized:
        n = normalized
        if n.get("maxParallelAgents") and n["maxParallelAgents"] > 1:
            stat_line = f", {n['maxParallelAgents']} parallel agents"
        elif n.get("longestStreakDays") and n["longestStreakDays"] > 1:
            stat_line = f", {n['longestStreakDays']}-day streak"
        elif n.get("totalSessions") and n["totalSessions"] > 0:
            stat_line = f", {n['totalSessions']} sessions"

    mode_label = mode_id.replace("-", " ")
    return f"{verb} in {mode_label} mode \u2014 strongest in {top1} and {top2}{stat_line}."


# ── Lab insight aggregation (experimental, never shareable) ─────────────────
#
# Admission rule: a Lab card must say something the main profile cannot —
# a pattern over time, a tension between signals, or a gap in the funnel.
# Stats already shown as wrapped cards (max parallel agents, deep sessions,
# plan mode, feature/fix ratio) are NOT restated here.

# Minimum data thresholds — below these a read is insufficient, not emitted
_LAB_MIN_SESSIONS = 10
_LAB_MIN_MONTHS = 2


def _month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def _monthly_series(
    sessions: list[Session], value_fn, min_per_month: int = 3
) -> tuple[list[str], list[float]]:
    """Aggregate a per-session value into a monthly mean series.

    *value_fn(session)* returns a number or None (skip). Months with fewer
    than *min_per_month* contributing sessions are dropped — a single
    session is an anecdote, not a month.
    """
    buckets: dict[str, list[float]] = {}
    for s in sessions:
        if not s.started_at:
            continue
        v = value_fn(s)
        if v is None:
            continue
        buckets.setdefault(_month_key(s.started_at), []).append(float(v))

    months = sorted(m for m, vals in buckets.items() if len(vals) >= min_per_month)
    values = [round(sum(buckets[m]) / len(buckets[m]), 1) for m in months]
    return months, values


def _trend_words(first: float, last: float) -> str:
    if first <= 0:
        return "steady"
    delta = (last - first) / first
    if delta >= 0.15:
        return "rising"
    if delta <= -0.15:
        return "falling"
    return "steady"


def build_experimental_signals(
    normalized: dict,
    git_data: dict | None = None,
    sessions: list[Session] | None = None,
) -> dict:
    """Build Lab insight cards from scan data.

    Tagged experimental and excluded from every shareable artifact.
    Card shape: {label, headline, detail, confidence, kind, series?,
    seriesLabels?}. Only emitted when the data honestly supports the
    read — thin data means no card, never an estimate.

    Returns ``{available: bool, signals: [...], codeIntelligence: []}``.
    """
    signals: list[dict] = []
    sessions = sessions or []
    total = normalized.get("totalSessions", 0) or len(sessions)
    enough_sessions = len(sessions) >= _LAB_MIN_SESSIONS

    # ── Delegation funnel: where does hands-off stop? ──
    if enough_sessions:

        def _has(s: Session, *keys: str) -> bool:
            calls = s.tool_calls_by_type or {}
            return any(calls.get(k, 0) > 0 for k in keys)

        n_sess = len(sessions)
        pct_edit = round(100 * sum(1 for s in sessions if _has(s, "file", "write")) / n_sess)
        pct_term = round(100 * sum(1 for s in sessions if _has(s, "terminal")) / n_sess)
        pct_mcp = round(100 * sum(1 for s in sessions if _has(s, "mcp")) / n_sess)
        pct_task = round(100 * sum(1 for s in sessions if _has(s, "task")) / n_sess)
        n_dispatch = sum((s.tool_calls_by_type or {}).get("task", 0) for s in sessions)
        max_par = normalized.get("maxParallelAgents", 0) or 0

        if max_par >= 3:
            stops = "runs agent fleets"
        elif pct_task > 0:
            stops = "dispatches subagents"
        elif max_par == 2:
            stops = "stops at two parallel agents"
        elif pct_mcp > 0:
            stops = "stops before subagents"
        elif pct_term > 0:
            stops = "stops before MCP tools"
        else:
            stops = "stays at file edits"
        signals.append(
            {
                "label": "Delegation funnel",
                "headline": stops,
                "detail": (
                    f"Of {n_sess} sessions: {pct_edit}% delegate file edits, "
                    f"{pct_term}% run terminal commands, {pct_mcp}% reach through "
                    f"MCP tools, {pct_task}% dispatch subagents "
                    f"({n_dispatch} dispatches); peak {max_par or 1} agent(s) in "
                    "parallel. The next rung of the funnel is where leverage "
                    "grows — if the work decomposes."
                ),
                "confidence": 75,
                "kind": "measured",
            }
        )

    # ── Prompt evolution: are your prompts getting richer or leaner? ──
    months, values = _monthly_series(
        sessions,
        lambda s: (
            (sum(s.prompt_word_counts) / len(s.prompt_word_counts))
            if s.prompt_word_counts
            else None
        ),
    )
    if len(months) >= _LAB_MIN_MONTHS:
        trend = _trend_words(values[0], values[-1])
        signals.append(
            {
                "label": "Prompt evolution",
                "headline": f"{trend}: {values[0]:.0f} → {values[-1]:.0f} words",
                "detail": (
                    f"Average prompt length per month, {months[0]} to {months[-1]}. "
                    "Longer prompts usually mean more constraints stated up front; "
                    "leaner prompts on the same work can mean the harness now "
                    "carries the context. Neither is better — the trend is yours."
                ),
                "confidence": 80,
                "kind": "measured",
                "series": values,
                "seriesLabels": months,
            }
        )

    # ── Correction loops: turns per session over time ──
    months, values = _monthly_series(sessions, lambda s: s.user_msgs if s.user_msgs > 0 else None)
    if len(months) >= _LAB_MIN_MONTHS:
        trend = _trend_words(values[0], values[-1])
        story = {
            "falling": "you're reaching done in fewer turns",
            "rising": "tasks are taking more back-and-forth — or getting bigger",
            "steady": "a stable conversational rhythm",
        }[trend]
        signals.append(
            {
                "label": "Correction loops",
                "headline": f"{trend}: {values[0]:.0f} → {values[-1]:.0f} turns",
                "detail": (
                    f"Average user turns per session by month — {story}. "
                    f"Window {months[0]} to {months[-1]}."
                ),
                "confidence": 70,
                "kind": "measured",
                "series": values,
                "seriesLabels": months,
            }
        )

    # ── Session rhythm: cadence of working weeks ──
    if enough_sessions:
        week_buckets: dict[str, int] = {}
        for s in sessions:
            if s.started_at:
                wk = s.started_at.strftime("%Y-%W")
                week_buckets[wk] = week_buckets.get(wk, 0) + 1
        if len(week_buckets) >= 4:
            weeks = sorted(week_buckets)
            series = [week_buckets[w] for w in weeks][-26:]
            active_weeks = len(week_buckets)
            peak = max(series)
            signals.append(
                {
                    "label": "Session rhythm",
                    "headline": f"{active_weeks} active weeks, peak {peak}/wk",
                    "detail": (
                        "Sessions per active week (last ~6 months shown). Bursts "
                        "and gaps are both visible — this is cadence, not a grade."
                    ),
                    "confidence": 80,
                    "kind": "measured",
                    "series": series,
                }
            )

    # ── Model routing: loyalist or router? ──
    if enough_sessions:
        with_models = [s for s in sessions if s.models]
        if len(with_models) >= _LAB_MIN_SESSIONS:
            multi = sum(1 for s in with_models if len(set(s.models)) > 1)
            distinct = len({m for s in with_models for m in s.models})
            pct_multi = round(100 * multi / len(with_models))
            style = (
                "routes between models mid-session"
                if pct_multi >= 20
                else "mostly one model per session"
            )
            signals.append(
                {
                    "label": "Model routing",
                    "headline": f"{distinct} models, {pct_multi}% multi-model",
                    "detail": (
                        f"{style}: {multi} of {len(with_models)} sessions used more "
                        "than one model. Routing by task is an orchestration "
                        "signal; loyalty is a consistency signal."
                    ),
                    "confidence": 70,
                    "kind": "measured",
                }
            )

    # ── Project interleaving: focus shape of an active day ──
    if enough_sessions:
        day_projects: dict[str, set] = {}
        for s in sessions:
            if s.started_at and s.project_path:
                day_projects.setdefault(s.started_at.strftime("%Y-%m-%d"), set()).add(
                    s.project_path
                )
        multi_days = [d for d, projs in day_projects.items() if len(projs) > 1]
        if len(day_projects) >= 10:
            pct = round(100 * len(multi_days) / len(day_projects))
            shape = "interleaved" if pct >= 40 else "single-project"
            signals.append(
                {
                    "label": "Focus shape",
                    "headline": f"{pct}% multi-project days",
                    "detail": (
                        f"On {pct}% of active days you touched more than one "
                        f"project — a mostly {shape} working style. Interleaving "
                        "suits orchestration; single-project days suit depth. "
                        "Different, not better."
                    ),
                    "confidence": 75,
                    "kind": "measured",
                }
            )

    # ── Context tension: scaffolding vs reference behavior ──
    context_tools: set[str] = set()
    scaffold_repos = 0
    deploy_tools: set[str] = set()
    automation_tools: set[str] = set()
    if git_data and git_data.get("projects"):
        for proj in git_data["projects"]:
            tools = proj.get("tools", [])
            if any(t in tools for t in ("CLAUDE.md", "Cursor Rules", "Cline Rules")):
                scaffold_repos += 1
            for tool in tools:
                if tool in ("CLAUDE.md", "Cursor Rules", "Cline Rules", "MCP"):
                    context_tools.add(tool)
                if tool in ("Docker", "Docker Compose", "Vercel", "Fly.io", "Netlify", "Render"):
                    deploy_tools.add(tool)
                if tool in ("GitHub Actions", "GitLab CI", "pre-commit"):
                    automation_tools.add(tool)

        n_repos = len(git_data["projects"])
        ref_rate = normalized.get("referenceUsageRate")
        if n_repos >= 3 and ref_rate is not None:
            if scaffold_repos == 0 and ref_rate >= 0.4:
                signals.append(
                    {
                        "label": "Context tension",
                        "headline": "reference-rich, scaffold-free",
                        "detail": (
                            f"{round(ref_rate * 100)}% reference-rich prompting but no "
                            f"CLAUDE.md/rules files in {n_repos} repos — you carry "
                            "context by hand each session. A context file would "
                            "bank what you keep retyping."
                        ),
                        "confidence": 65,
                        "kind": "measured",
                    }
                )
            elif scaffold_repos > 0:
                pct_repos = round(100 * scaffold_repos / n_repos)
                signals.append(
                    {
                        "label": "Context scaffolding",
                        "headline": f"{scaffold_repos} of {n_repos} repos ({pct_repos}%)",
                        "detail": (
                            f"Repos with agent context files ({', '.join(sorted(context_tools))}). "
                            "Scaffolded repos let agents start warm; the unscaffolded "
                            "ones are the cheapest leverage still on the table."
                        ),
                        "confidence": 75,
                        "kind": "measured",
                    }
                )

    # ── Harness inventory: how this builder tools their agents ──
    harness = build_harness_summary(git_data, sessions)
    inv_parts = []
    if harness["skills"]:
        inv_parts.append(f"{harness['skills']} skills")
    if harness["agents"]:
        inv_parts.append(f"{harness['agents']} custom agents")
    if harness["commands"]:
        inv_parts.append(f"{harness['commands']} commands")
    if harness["hooks"]:
        inv_parts.append(f"{harness['hooks']} hooks")
    if harness["rules"]:
        inv_parts.append(f"{harness['rules']} rule files")
    if harness["plugins"]:
        inv_parts.append(f"{harness['plugins']} plugin(s)")
    if inv_parts:
        md_note = (
            f" CLAUDE.md in {harness['claudeMdRepos']} repos "
            f"({harness['claudeMdLines']} lines total)."
            if harness["claudeMdRepos"]
            else ""
        )
        signals.append(
            {
                "label": "Harness inventory",
                "headline": ", ".join(inv_parts[:3]),
                "detail": (
                    f"Agent tooling across your repos: {', '.join(inv_parts)}."
                    f"{md_note} This is the craft of making agents start warm — "
                    "skills, subagents, commands, and hooks are reusable leverage."
                ),
                "confidence": 80,
                "kind": "measured",
            }
        )
    elif harness["claudeMdRepos"]:
        signals.append(
            {
                "label": "Harness inventory",
                "headline": f"CLAUDE.md x {harness['claudeMdRepos']}",
                "detail": (
                    f"CLAUDE.md in {harness['claudeMdRepos']} repos "
                    f"({harness['claudeMdLines']} lines total) — context files are "
                    "the first rung; skills, custom agents, and hooks are the next."
                ),
                "confidence": 75,
                "kind": "measured",
            }
        )

    # ── Tool environment (not shown elsewhere) ──
    mcp_count = normalized.get("mcpServerCount", 0)
    mcp_calls = normalized.get("mcpToolCalls", 0)
    if mcp_count > 0:
        signals.append(
            {
                "label": "MCP integrations",
                "headline": f"{mcp_count} server{'s' if mcp_count != 1 else ''}",
                "detail": f"{mcp_count} MCP servers configured, {mcp_calls} tool calls observed.",
                "confidence": 80,
                "kind": "measured",
            }
        )
    if deploy_tools:
        signals.append(
            {
                "label": "Deploy readiness",
                "headline": ", ".join(sorted(deploy_tools)),
                "detail": f"Deploy infrastructure detected: {', '.join(sorted(deploy_tools))}.",
                "confidence": 80,
                "kind": "measured",
            }
        )
    if automation_tools:
        signals.append(
            {
                "label": "Automations",
                "headline": ", ".join(sorted(automation_tools)),
                "detail": f"CI/automation configs found: {', '.join(sorted(automation_tools))}.",
                "confidence": 80,
                "kind": "measured",
            }
        )

    # ── Self-trends: you vs your own history (the only honest comparator) ──
    trend_pairs = [
        (
            "recentPlanRatio",
            "historicalPlanRatio",
            "Planning trend",
            "share of work preceded by plan artifacts",
        ),
        ("recentModelCount", "historicalModelCount", "Model range trend", "distinct models in use"),
        (
            "recentLanguageCount",
            "historicalLanguageCount",
            "Language range trend",
            "distinct languages committed",
        ),
    ]
    for recent_key, hist_key, label, what in trend_pairs:
        recent = normalized.get(recent_key)
        hist = normalized.get(hist_key)
        if recent is None or hist is None or hist <= 0:
            continue
        delta = (recent - hist) / hist
        if abs(delta) < 0.25:
            continue  # no meaningful movement — no card
        direction = "up" if delta > 0 else "down"
        signals.append(
            {
                "label": label,
                "headline": f"{direction} {abs(round(delta * 100))}% vs your history",
                "detail": (
                    f"Your recent {what} ({recent:g}) against your own earlier "
                    f"baseline ({hist:g}). Compared only to you — there is no cohort."
                ),
                "confidence": 60,
                "kind": "measured",
            }
        )

    _ = total  # reserved for future per-total reads
    return {
        "available": len(signals) > 0,
        "signals": signals,
        "codeIntelligence": [],  # populated by the opt-in --code scan
    }


# ── COVERAGE REPORT ──────────────────────────────────────────────────────────

_SOURCE_LABELS = {
    "claude_code": "Claude Code",
    "cursor": "Cursor IDE",
    "codex": "Codex CLI",
    "kiro": "Kiro",
    "git": "git",
    "other_tools": (
        "Other AI tools (VS Code Copilot/Cline/Cody, Continue, Aider, Windsurf, Zed, JetBrains)"
    ),
    "local_models": "Local model runtimes (Ollama/LM Studio/llama.cpp)",
    "claude_desktop": "Claude Desktop",
}


def build_coverage_report(
    enabled_sources: dict,
    collection_config: dict | None,
    detected_sources: dict,
    raw_data: dict,
    git_data: dict | None,
    code_scan_ran: bool = False,
) -> dict:
    """What exists on this machine that was NOT collected, and the one
    knob that widens each gap.

    Honesty rule: when more data would help, the answer is a calibrate
    question/flag (default maximal) — never an estimate. This report is
    private (Details/provenance only, never shareable).
    """
    config = collection_config or {}
    sources: list[dict] = []
    gaps: list[dict] = []

    for key, label in _SOURCE_LABELS.items():
        detected = bool(detected_sources.get(key, False))
        consented = bool(enabled_sources.get(key, False))
        collected = bool(git_data) if key == "git" else raw_data.get(key) is not None
        entry = {
            "id": key,
            "label": label,
            "detectedOnMachine": detected,
            "consented": consented,
            "collected": collected,
        }
        if detected and not consented:
            knob = (
                f"{cli_invocation()} calibrate — answer yes to Claude Desktop (experimental)"
                if key == "claude_desktop"
                else f"{cli_invocation()} calibrate — enable {label}"
            )
            entry["gap"] = f"{label} data exists on this machine but consent is off."
            entry["widen"] = knob
            gaps.append({"source": key, "gap": entry["gap"], "widen": knob})
        sources.append(entry)

    window = config.get("window", "all")
    window_entry = {"value": window}
    if window != "all":
        window_entry["gap"] = (
            f"Collection window is {window} days; history beyond it is not scanned."
        )
        window_entry["widen"] = f"{cli_invocation()} calibrate — set window to all-time"
        gaps.append(
            {"source": "window", "gap": window_entry["gap"], "widen": window_entry["widen"]}
        )

    repos_cfg = config.get("repos", "all")
    repos_entry: dict = {"value": "all" if repos_cfg == "all" else len(repos_cfg)}
    if isinstance(repos_cfg, list):
        repos_entry["gap"] = (
            f"Repo filter limits scanning to {len(repos_cfg)} repos; "
            "other local repos are not scanned."
        )
        repos_entry["widen"] = f"{cli_invocation()} calibrate — set repos to all"
        gaps.append({"source": "repos", "gap": repos_entry["gap"], "widen": repos_entry["widen"]})

    code_entry: dict = {"ran": code_scan_ran}
    if not code_scan_ran:
        code_entry["gap"] = "Local code scan (structure, deps, tests, deploy configs) not run."
        code_entry["widen"] = f"{cli_invocation()} assess --code (opt-in, metrics only)"
        gaps.append({"source": "code_scan", "gap": code_entry["gap"], "widen": code_entry["widen"]})

    return {
        "sources": sources,
        "window": window_entry,
        "repos": repos_entry,
        "codeScan": code_entry,
        "gaps": gaps,
        "complete": len(gaps) == 0,
    }


# ── HARNESS SUMMARY (the 2026 craft inventory) ──────────────────────────────


def build_harness_summary(git_data: dict | None, sessions: list[Session] | None = None) -> dict:
    """Aggregate agent-harness signals across repos + sessions.

    skills/agents/commands/hooks/rules counts, CLAUDE.md richness, MCP
    repos, and dispatched subagents (Task tool calls). Derived counts —
    a flex signal of how someone tools their agents, never a ranking.
    """
    sessions = sessions or []
    totals = {
        "skills": 0,
        "agents": 0,
        "commands": 0,
        "hooks": 0,
        "rules": 0,
        "plugins": 0,
        "claudeMdRepos": 0,
        "claudeMdLines": 0,
        "mcpRepos": 0,
        "scaffoldedRepos": 0,
        "totalRepos": 0,
        "subagentDispatches": 0,
        "sessionsWithSubagents": 0,
    }

    if git_data and git_data.get("projects"):
        totals["totalRepos"] = len(git_data["projects"])
        for proj in git_data["projects"]:
            h = proj.get("harness") or {}
            totals["skills"] += h.get("skills", 0)
            totals["agents"] += h.get("agents", 0)
            totals["commands"] += h.get("commands", 0)
            totals["hooks"] += h.get("hooks", 0)
            totals["rules"] += h.get("rules", 0)
            totals["plugins"] += h.get("plugin", 0)
            if h.get("claudeMdLines"):
                totals["claudeMdRepos"] += 1
                totals["claudeMdLines"] += h["claudeMdLines"]
            tools = set(proj.get("tools", []))
            if "MCP" in tools:
                totals["mcpRepos"] += 1
            if tools & {
                "CLAUDE.md",
                "Cursor Rules",
                "Cline Rules",
                "MCP",
                "Skills",
                "Agents",
                "Commands",
                "Hooks",
            }:
                totals["scaffoldedRepos"] += 1

    for s in sessions:
        task_calls = (s.tool_calls_by_type or {}).get("task", 0)
        if task_calls:
            totals["subagentDispatches"] += task_calls
            totals["sessionsWithSubagents"] += 1

    totals["available"] = any(v for k, v in totals.items() if k not in ("totalRepos", "available"))
    return totals


# ── CONFIDENCE (honest, variable, explainable) ──────────────────────────────

# The NormalizedMetrics slots that count toward completeness — mirrors
# schema.NormalizedMetrics. A profile with thin sources fills few of these.
_CONFIDENCE_METRIC_SLOTS = 46
_ALL_STANDARD_SOURCES = 4  # claude_code, cursor, codex, git

# A dimension scored from fewer than this many underlying events is marked
# *provisional* — its score is kept (never zeroed: a light-but-skilled builder
# isn't punished), but it's flagged as a small sample and doesn't anchor a
# confident composite. The per-dimension sample mapping is a reasoned-default
# (documented in SCORING-METHODOLOGY.md §2): build/recovery rest on AI-attributed
# commits, decision on plans, the rest on sessions.
_MIN_DIM_SAMPLE = 10


def _dimension_samples(normalized: dict, signals: dict) -> dict:
    sessions = normalized.get("totalSessions") or 0
    commits = signals.get("scored_commits") or normalized.get("totalScoredCommits") or 0
    plans = signals.get("architecture_plans") or normalized.get("planCount") or 0
    return {
        "signal_clarity": sessions,
        "build_stability": commits,
        "decision_weight": plans,
        "recovery_velocity": commits,
        "context_command": sessions,
        "orchestration_range": sessions,
    }


def mark_dimension_sufficiency(dims: dict, normalized: dict, signals: dict) -> None:
    """Attach sampleSize + provisional to each scored dimension, in place.

    Representation of how much evidence backs a score — never a change to the
    score. A score from 7 commits is the same number, just honestly flagged as a
    small sample so it reads as provisional, not a confident verdict.
    """
    samples = _dimension_samples(normalized, signals or {})
    for dim_id, d in dims.items():
        if not isinstance(d, dict) or d.get("score") is None:
            continue
        n = samples.get(dim_id, 0)
        d["sampleSize"] = n
        d["provisional"] = n < _MIN_DIM_SAMPLE


def build_confidence(
    normalized: dict,
    sources_used: list,
    span_days: int,
    total_sessions: int,
    dims: dict | None = None,
    active_hours: float = 0.0,
    active_days: int = 0,
    code_scan_ran: bool = False,
) -> dict:
    """Confidence in the assessment, 0-100, from what was actually measured.

    Five factors that reward SUBSTANCE over raw counts — never pinned at 100:
      completeness: populated metric slots / all slots                     (25%)
      sources:      collected sources / standard sources                   (20%)
      depth:        fraction of scored dimensions on a sufficient sample   (30%)
      volume:       active hands-on hours toward 40                        (15%)
      window:       AI-era active days toward 90 (density, not raw span)   (10%)
    Depth is the biggest factor: many short sessions over a long, sparse span no
    longer buys confidence the way it used to — small-sample dimensions hold it
    down. Capped at 98; the last points belong to the opt-in code scan.
    """
    populated = sum(1 for v in normalized.values() if v not in (None, "", [], {}))
    completeness = min(populated / _CONFIDENCE_METRIC_SLOTS, 1.0)
    sources = min(len(sources_used) / _ALL_STANDARD_SOURCES, 1.0)
    volume = min((active_hours or 0) / 40, 1.0)
    window = min((active_days or 0) / 90, 1.0)
    scored = [
        d for d in (dims or {}).values() if isinstance(d, dict) and d.get("score") is not None
    ]
    sufficient = [d for d in scored if not d.get("provisional")]
    depth = (len(sufficient) / len(scored)) if scored else 1.0

    score = round(completeness * 25 + sources * 20 + depth * 30 + volume * 15 + window * 10)
    cap = 98 if code_scan_ran else 95
    score = max(0, min(score, cap))

    return {
        "score": score,
        "factors": {
            "completeness": {
                "pct": round(completeness * 100),
                "detail": f"{populated} of {_CONFIDENCE_METRIC_SLOTS} metric slots measured",
            },
            "sources": {
                "pct": round(sources * 100),
                "detail": (
                    f"{len(sources_used)} of {_ALL_STANDARD_SOURCES} standard sources collected"
                ),
            },
            "depth": {
                "pct": round(depth * 100),
                "detail": (
                    f"{len(sufficient)} of {len(scored)} dimensions on a sufficient sample"
                    if scored
                    else "no dimensions scored"
                ),
            },
            "volume": {
                "pct": round(volume * 100),
                "detail": f"{round(active_hours or 0, 1)}h active (40h = full weight)",
            },
            "window": {
                "pct": round(window * 100),
                "detail": f"{active_days or 0} active days (90 = full weight)",
            },
        },
    }


# ── PROJECT ORCHESTRATION (per-repo loop evidence) ───────────────────────────


def build_project_orchestration(sessions: list[Session]) -> dict:
    """Per-project orchestration evidence: subagent dispatches (Task tool)
    and overlapping same-project sessions. Feeds the positioning footprint
    so 'designs the loop' lights up where the loops actually ran."""
    by_proj: dict[str, dict] = {}
    spans: dict[str, list] = {}
    for s in sessions:
        if not s.project_path:
            continue
        entry = by_proj.setdefault(
            s.project_path, {"dispatches": 0, "sessionsWithDispatch": 0, "maxParallel": 1}
        )
        task_calls = (s.tool_calls_by_type or {}).get("task", 0)
        if task_calls:
            entry["dispatches"] += task_calls
            entry["sessionsWithDispatch"] += 1
        if s.started_at and s.ended_at:
            spans.setdefault(s.project_path, []).append((s.started_at, s.ended_at))

    # Same-project parallel sessions: max concurrent overlap
    for path, ivs in spans.items():
        events = []
        for a, b in ivs:
            events.append((a, 1))
            events.append((b, -1))
        events.sort(key=lambda e: (e[0], e[1]))
        cur = peak = 0
        for _, delta in events:
            cur += delta
            peak = max(peak, cur)
        by_proj[path]["maxParallel"] = max(by_proj[path]["maxParallel"], peak)

    return {k: v for k, v in by_proj.items() if v["dispatches"] or v["maxParallel"] > 1}


# ── AI leverage: measured output facts + a labeled counterfactual band ───────


def build_leverage_signal(cursor_data: dict | None, normalized: dict) -> dict | None:
    """What AI built with you, in counted lines — plus the one question
    everyone asks ("how long without AI?") answered the only honest way.

    MEASURED (pure counts, main surfaces): AI-authored vs hand-written
    lines that SURVIVED in tracked commits (Cursor per-commit authorship
    attribution), the resulting AI share and output multiple, hands-on
    hours, agent runtime.

    ESTIMATE (Lab/experimental only, never a score input): the
    solo-equivalent time RANGE. Controlled studies of AI-assisted coding
    report roughly 25–50% task-time savings (so the same output solo ≈
    1.33–2× the time) — and the research is mixed: one 2025 RCT measured
    experienced devs SLOWER on familiar code. We therefore show a band
    anchored to that literature, applied to the user's own measured
    hands-on hours, labeled estimate — never a single flattering number.

    Returns None (insufficient) below 10 tracked commits or 1000
    attributed lines — never estimated from thin data.
    """
    sc = (cursor_data or {}).get("scored_commits") or {}
    tracked = sc.get("totalCommits") or 0
    ai_lines = sc.get("totalAiLines") or 0
    human_lines = sc.get("totalHumanLines") or 0
    total_lines = ai_lines + human_lines

    if tracked < 10 or total_lines < 1000:
        return None

    ai_share = round(ai_lines / total_lines * 100, 1)
    # Output multiple: shipped lines vs the hand-written share alone.
    # When virtually everything is AI-authored the ratio explodes — cap
    # the DISPLAY at 50× and say so, rather than print a silly number.
    output_multiple: float | None
    if human_lines > 0:
        output_multiple = round(min(total_lines / human_lines, 50.0), 1)
    else:
        output_multiple = None  # all tracked lines AI-authored

    hours = normalized.get("totalEstimatedHours") or 0
    solo_low = round(hours * 1.33) if hours else None
    solo_high = round(hours * 2.0) if hours else None

    return {
        "aiShare": ai_share,
        "aiLines": ai_lines,
        "humanLines": human_lines,
        "trackedCommits": tracked,
        "outputMultiple": output_multiple,
        "outputMultipleCapped": bool(output_multiple == 50.0),
        "handsOnHours": hours,
        "agentHours": normalized.get("agentRuntimeHours") or 0,
        "soloEquivalentHours": (
            {"low": solo_low, "high": solo_high} if solo_low and solo_high else None
        ),
        "basis": (
            f"Per-commit authorship attribution over {tracked} tracked commits "
            "(Cursor scored commits — commits without attribution are not counted)."
        ),
        "estimateNote": (
            "Solo-equivalent time is a research-anchored BAND (studies report "
            "~25–50% task-time savings with AI assistance; evidence is mixed — "
            "one 2025 RCT found experienced devs slower on familiar code), "
            "applied to your measured hands-on hours. An estimate, never a score."
        ),
    }
