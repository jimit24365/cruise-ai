#!/usr/bin/env python3
"""
cruise_ai — Build your AI coding profile.

Scans your AI coding sessions (Claude Code, Cursor IDE, Codex CLI),
scores your profile across 6 dimensions and 9 archetypes,
and optionally starts a local profile server.

Subcommands:
    cruise_ai calibrate    # Onboarding: consent + collection scope
    cruise_ai assess       # Scan + score + write assessment JSON
    cruise_ai report       # Start local profile server
    cruise_ai sources      # Show discovered data sources
    cruise_ai enrich       # (Step 5) AI narrative enrichment

Legacy flags still work:
    cruise_ai --serve      # assess + report
    cruise_ai --preview    # Show collected scan data
    cruise_ai --tools      # List detected AI tools
    cruise_ai --yes        # Non-interactive (accept all sources)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from cruise_ai import __version__
from cruise_ai.paths import cli_invocation


def run_scan(project_filter=None, enabled_sources=None, collection_config=None, code_scan=False):
    """Run the full scanner pipeline and return the result dict.

    *enabled_sources*: ``{"claude_code": bool, "cursor": bool, ...}``
    controls which scanners run. ``None`` enables all standard sources
    (experimental sources stay off).

    *collection_config*: ``{"window": "all"|int, "repos": "all"|list}``
    controls git scanning scope. ``None`` uses defaults.

    *code_scan*: opt-in local code scan (``assess --code``) — reads repo
    files to metrics only; nothing stored, nothing sent.

    Uses the adapter registry to discover and run adapters, then
    computes both legacy ``normalized`` metrics and the new
    ``signal_matrix``.
    """
    from cruise_ai.adapters._registry import get_session_adapters, run_adapters
    from cruise_ai.aggregator import (
        build_activity_by_day,
        build_coverage_report,
        build_experimental_signals,
        build_models_summary,
        build_scanned_projects,
        build_signal_matrix,
        build_stack_summary,
    )
    from cruise_ai.scanner import build_summary, compute_normalized, iso_now
    from cruise_ai.schema import SCHEMA_VERSION

    if enabled_sources is None:
        from cruise_ai.consent import default_enabled_sources

        enabled_sources = default_enabled_sources()

    pf = None
    if project_filter:
        pf = str(Path(os.path.expanduser(project_filter)).resolve())

    # Run adapters — returns Session objects + raw data dicts
    sessions, raw_data, git_data = run_adapters(pf, enabled_sources, collection_config)

    # Adapters that mark orchestration via child sessions (kiro) get their
    # parents credited with task dispatches BEFORE anything consumes
    # tool_calls_by_type (harness, ledger, signal matrix).
    from cruise_ai.aggregator import attribute_subagent_dispatches, fold_session_metrics

    attribute_subagent_dispatches(sessions)

    # Extract per-tool raw data for backward compatibility
    claude_data = raw_data.get("claude_code")
    cursor_data = raw_data.get("cursor")
    codex_data = raw_data.get("codex")

    # Legacy normalized metrics (still used by scoring engine)
    normalized = compute_normalized(
        claude_data,
        cursor_data,
        codex_data,
        git_data,
        desktop_data=raw_data.get("claude_desktop"),
        cursor_consented=bool((enabled_sources or {}).get("cursor")),
    )

    # Fold session-derived signals from every OTHER deep session source
    # (kiro, codex, deep wider-field) into the same measured metrics —
    # compute_normalized only reads the claude/cursor raw dicts.
    fold_session_metrics(normalized, sessions, claude_data, cursor_data)

    # Cross-surface breadth: distinct tools with at least one PARSED
    # session — usage evidence for Context Command (v0.4.0), never mere
    # detection (a counts/presence-tier tool contributes nothing here).
    normalized["activeSurfaceCount"] = len({s.tool for s in sessions if s.session_id})

    # New signal matrix from Session objects
    signal_matrix = build_signal_matrix(sessions)

    tools_detected = []
    if claude_data:
        tools_detected.append("claude_code")
    if cursor_data:
        tools_detected.append("cursor_ide")
    if codex_data:
        tools_detected.append("codex_cli")

    # Wider tool field (other_tools consent group): collect raw payloads
    # with their declared fidelity; presence/counts tools contribute
    # provenance, never invented sessions.
    _core_keys = {"claude_code", "cursor", "codex", "claude_desktop"}
    other_tools = {
        name: payload
        for name, payload in raw_data.items()
        if name not in _core_keys and payload is not None
    }
    tools_detected.extend(sorted(other_tools.keys()))

    # Local model runtimes (Ollama / LM Studio / llama.cpp) — model-usage
    # evidence, not sessions. Detection (presence) always runs so coverage
    # can honestly say "exists but consent off"; collection is gated.
    from cruise_ai.adapters.local_models import detect_local_models

    _local_models_present = detect_local_models()
    local_models = _local_models_present if enabled_sources.get("local_models", False) else None

    summary = build_summary(claude_data, cursor_data, codex_data, git_data, normalized)

    # Front-end view data (all derived from real session/git data)
    activity_by_day = build_activity_by_day(sessions, cursor_data, git_data)
    from cruise_ai.aggregator import build_harness_summary

    harness = build_harness_summary(git_data, sessions)

    # ── Durable history: evidence survives session pruning + repo deletion ──
    # The ledger is append-only and local-only (~/.cruise_ai/data/history)
    from cruise_ai.history import (
        ledger_orchestration,
        ledger_totals,
        update_activity_history,
        update_session_ledger,
    )

    ledger = update_session_ledger(sessions)
    durable = ledger_orchestration(ledger)
    project_orchestration = durable["perProject"]

    # Subagent dispatches are first-class leverage evidence — durable
    # totals (ledger) supersede live-only counts, because those runs
    # happened and were measured even if their files are gone now.
    normalized["subagentDispatches"] = durable["subagentDispatches"]
    normalized["sessionsWithSubagents"] = durable["sessionsWithSubagents"]
    normalized["maxParallelAgents"] = max(
        normalized.get("maxParallelAgents", 0) or 0, durable["maxParallelAgents"]
    )
    harness["subagentDispatches"] = durable["subagentDispatches"]
    harness["sessionsWithSubagents"] = durable["sessionsWithSubagents"]

    # Same rule for sessions / hours / span: tools prune their stores,
    # the ledger does not. max() — measured history never regresses.
    totals = ledger_totals(ledger)
    normalized["totalSessions"] = max(normalized.get("totalSessions", 0) or 0, totals["sessions"])
    normalized["totalEstimatedHours"] = max(
        normalized.get("totalEstimatedHours", 0) or 0, totals["estimatedHours"]
    )
    normalized["aiUsageSpanDays"] = max(
        normalized.get("aiUsageSpanDays", 0) or 0, totals["spanDays"]
    )
    normalized["longestSessionMinutes"] = max(
        normalized.get("longestSessionMinutes", 0) or 0, totals["longestSessionMinutes"]
    )
    normalized["deepSessionCount"] = max(
        normalized.get("deepSessionCount", 0) or 0, totals["deepSessionCount"]
    )
    normalized["marathonSessionCount"] = totals["marathonSessionCount"]
    # Agent runtime: subagents working under dispatched runs — kept
    # separate from the user's own session hours (parallel agent-time,
    # never added into "time you put in")
    live_agent_hours = (claude_data or {}).get("agent_hours", 0) or 0
    live_agent_runs = (claude_data or {}).get("subagent_runs", 0) or 0
    normalized["agentRuntimeHours"] = max(live_agent_hours, totals["agentHours"])
    normalized["subagentRunCount"] = max(live_agent_runs, totals["agentRuns"])
    # Keep the human-readable summary consistent with the durable truth
    summary["total_sessions"] = normalized["totalSessions"]
    summary["ai_usage_span_days"] = normalized["aiUsageSpanDays"]

    # Per-day activity is a UNION across all scans ever made
    activity_by_day = update_activity_history(activity_by_day)
    # Clamp the AI-activity surface to the user's AI era (see tag_ai_era).
    _ai_era_start = min(
        (s.started_at.strftime("%Y-%m-%d") for s in sessions if s.started_at),
        default=None,
    )
    _ai_era_days = tag_ai_era(activity_by_day, _ai_era_start)
    # The streak reads the AI-era union — spans tools, excludes pre-AI git.
    normalized["longestStreakDays"] = max(
        normalized.get("longestStreakDays", 0) or 0, _longest_streak(_ai_era_days)
    )
    scanned_projects = build_scanned_projects(sessions, git_data)
    stack_summary = build_stack_summary(git_data)
    models_summary = build_models_summary(sessions, raw_data)
    if local_models:
        # Local/offline runtimes appear alongside cloud models — listed,
        # never merged into byModel counts (different units of evidence)
        models_summary["localRuntimes"] = local_models["runtimes"]
    experimental = build_experimental_signals(normalized, git_data, sessions)

    # AI leverage: measured authorship facts (main surfaces) + the
    # solo-equivalent counterfactual as a labeled Lab ESTIMATE
    from cruise_ai.aggregator import build_leverage_signal

    leverage = build_leverage_signal(cursor_data, normalized)
    if leverage and leverage.get("soloEquivalentHours"):
        seh = leverage["soloEquivalentHours"]
        experimental["signals"].append(
            {
                "label": "Solo-equivalent time",
                "headline": f"~{seh['low']:,}–{seh['high']:,}h",
                "detail": (
                    f"Your {leverage['handsOnHours']:,.0f} measured hands-on hours "
                    f"shipped {leverage['aiLines']:,} AI-authored lines "
                    f"({leverage['aiShare']}% of tracked output). " + leverage["estimateNote"]
                ),
                "confidence": 40,
                "kind": "estimate",
            }
        )
        experimental["available"] = True

    # Claude Desktop (experimental, opt-in): surfaces as an experimental
    # signal only — it never feeds normalized metrics or scores.
    desktop_data = raw_data.get("claude_desktop")
    if desktop_data and desktop_data.get("mcpServerCount", 0) > 0:
        experimental["signals"].append(
            {
                "label": "Claude Desktop MCPs",
                "headline": f"{desktop_data['mcpServerCount']} servers",
                "detail": (
                    f"MCP servers configured in Claude Desktop: "
                    f"{', '.join(desktop_data['mcpServers'][:6])}. "
                    "Low-fidelity source: install + config only."
                ),
                "confidence": 40,
                "kind": "estimate",
            }
        )
        experimental["available"] = True

    # Opt-in local code scan (metrics only — content never stored/sent)
    code_intel_result = None
    if code_scan:
        from cruise_ai.code_intel import scan_repos

        repo_paths: list[str] = []
        if git_data and git_data.get("projects"):
            repo_paths = [p.get("path") for p in git_data["projects"] if p.get("path")]
        code_intel_result = scan_repos(repo_paths)
        experimental["codeIntelligence"] = code_intel_result["codeIntelligence"]
        if code_intel_result["codeIntelligence"]:
            experimental["available"] = True

    # Coverage: what exists here that wasn't collected + the knob to widen
    detected = {a.name: a.detect() for a in get_session_adapters()}
    detected["git"] = bool(git_data) or enabled_sources.get("git", False)
    # Group-level rollups for the two new consent groups. Kiro has its own
    # consent key + coverage row (its payload merely LIVES under otherTools),
    # so it must not light the other_tools rollup or satisfy its row.
    detected["other_tools"] = any(
        v for k, v in detected.items() if k not in _core_keys | {"git", "kiro"}
    )
    detected["local_models"] = _local_models_present is not None
    coverage_raw = dict(raw_data)
    coverage_raw["other_tools"] = {k: v for k, v in other_tools.items() if k != "kiro"} or None
    coverage_raw["local_models"] = local_models
    coverage = build_coverage_report(
        enabled_sources,
        collection_config,
        detected,
        coverage_raw,
        git_data,
        code_scan_ran=code_scan,
    )

    from cruise_ai import __version__ as _pkg_version
    from cruise_ai.schema import METHODOLOGY_VERSION, TAXONOMY_VERSION

    return {
        "schema_version": SCHEMA_VERSION,
        "engine": {
            "schema": SCHEMA_VERSION,
            "taxonomy": TAXONOMY_VERSION,
            "methodology": METHODOLOGY_VERSION,
            "package": _pkg_version,
        },
        "scanned_at": iso_now(),
        "tools_detected": tools_detected,
        "summary": summary,
        "claude_code": claude_data,
        "cursor": cursor_data,
        "codex": codex_data,
        "git": git_data,
        "claude_desktop": desktop_data,
        "otherTools": other_tools,
        "localModels": local_models,
        "normalized": normalized,
        "signal_matrix": signal_matrix,
        "activityByDay": activity_by_day,
        "projects": scanned_projects,
        "stack": stack_summary,
        "models": models_summary,
        "harness": harness,
        "projectOrchestration": project_orchestration,
        "leverage": leverage,
        "experimental": experimental,
        "code_intel": code_intel_result,
        "coverage": coverage,
    }


def show_preview():
    """Print a summary of scan_results.json to stdout."""
    from cruise_ai.paths import scan_results_path

    sr = scan_results_path()
    if not sr.is_file():
        print("  No scan data yet. Run `cruise_ai assess` first.")
        return

    with open(sr) as f:
        data = json.load(f)

    print()
    print("  SCAN DATA PREVIEW")
    print("  " + "=" * 42)
    print()
    print(f"  Scanned at: {data.get('scanned_at', 'unknown')}")
    print(f"  Schema version: {data.get('schema_version', 'unknown')}")
    print(f"  Tools detected: {', '.join(data.get('tools_detected', [])) or 'none'}")
    print()

    summary = data.get("summary", {})
    print("  Summary:")
    print(f"    Total sessions:       {summary.get('total_sessions', 0)}")
    print(f"    Total AI code blocks: {summary.get('total_ai_blocks', 0)}")
    print(f"    Total scored commits: {summary.get('total_scored_commits', 0)}")
    print(f"    Total plans:          {summary.get('total_plans', 0)}")
    print(f"    Total projects:       {summary.get('total_projects', 0)}")
    print(f"    AI usage span (days): {summary.get('ai_usage_span_days', 0)}")
    models = summary.get("models_used", [])
    if models:
        print(f"    Models used:          {', '.join(models[:10])}")
    print()

    # Per-source overview
    claude = data.get("claude_code")
    if claude:
        print("  Claude Code:")
        print(f"    Sessions: {claude.get('total_sessions', 0)}")
        print(f"    Messages: {claude.get('total_messages', 0)}")
        print()

    cursor = data.get("cursor")
    if cursor:
        print("  Cursor IDE:")
        ai_code = cursor.get("ai_code") or {}
        print(f"    AI code blocks: {ai_code.get('totalHashes', 0)}")
        scored = cursor.get("scored_commits") or {}
        print(f"    Scored commits: {scored.get('totalCommits', 0)}")
        convos = cursor.get("conversations") or {}
        print(f"    Conversations:  {convos.get('total_conversations', 0)}")
        plans = cursor.get("plans") or {}
        print(f"    Plans:          {plans.get('totalPlans', 0)}")
        print()

    codex = data.get("codex")
    if codex:
        print("  Codex CLI:")
        print(f"    Sessions: {codex.get('total_sessions', 0)}")
        print()

    kiro = (data.get("otherTools") or {}).get("kiro")
    if kiro:
        print("  Kiro:")
        print(f"    Sessions: {kiro.get('total_sessions', 0)}")
        print(
            f"    Messages: {kiro.get('total_user_msgs', 0) + kiro.get('total_assistant_msgs', 0)}"
        )
        if kiro.get("subagent_sessions"):
            print(f"    Subagent sessions: {kiro.get('subagent_sessions', 0)}")
        print()

    git = data.get("git")
    if git:
        projects = git.get("projects", [])
        print(f"  Git: {len(projects)} project(s)")
        for p in projects[:10]:
            print(f"    {p.get('name', '?')}: {p.get('commits_6m', 0)} commits")
        if len(projects) > 10:
            print(f"    ... and {len(projects) - 10} more")
        print()

    print("  This data never leaves your machine.")
    print("  Full disclosure: DATA_COLLECTION.md")
    print()


# ── Honest progress messages ────────────────────────────────────────────────


def _print_signal_insights(scan_results: dict) -> None:
    """Print honest, signal-linked progress messages from real scan data.

    Only prints insights backed by actual metrics. Thin data is stated honestly.
    """
    summary = scan_results.get("summary", {})
    normalized = scan_results.get("normalized", {})

    total_sessions = summary.get("total_sessions", 0)
    total_projects = summary.get("total_projects", 0)
    tools_found = scan_results.get("tools_detected", [])
    span_days = summary.get("ai_usage_span_days", 0)

    # Basic scan summary
    tool_count = len(tools_found)
    print(
        f"        Scanned {total_projects} repos, {total_sessions} sessions"
        f" across {tool_count} tool{'s' if tool_count != 1 else ''}"
    )

    if span_days > 0:
        print(f"        AI sessions span {span_days} days (ledger-preserved)")
    # The evidence range is wider than the session span: git commits and
    # day-union history reach further back than any tool's session store
    _act = scan_results.get("activityByDay", [])
    _dates = [d["date"] for d in _act if d.get("date")]
    if _dates and _dates[0][:10] != _dates[-1][:10]:
        print(f"        Evidence range (sessions + commits): {_dates[0]} to {_dates[-1]}")
    _agent_h = scan_results.get("normalized", {}).get("agentRuntimeHours", 0)
    if _agent_h:
        _runs = scan_results.get("normalized", {}).get("subagentRunCount", 0)
        print(f"        Your agents worked {_agent_h}h across {_runs} subagent runs")

    # Thin data warning
    if total_sessions < 5:
        print(f"        Limited data — {total_sessions} sessions found. Confidence will be low.")
        return

    # Signal-linked insights (only if data supports them)
    # Streak detection from activityByDay
    activity = scan_results.get("activityByDay", [])
    if activity:
        streak = _longest_streak(activity)
        if streak >= 3:
            print(f"        You ship in focused bursts — {streak}-day streak detected.")

    # Tool call ratio
    tool_call_ratio = normalized.get("toolCallRatio", 0)
    total_tool_calls = normalized.get("totalToolCalls", 0)
    if tool_call_ratio > 0.5 and total_tool_calls > 50:
        print(
            f"        Agent-heavy workflow — {total_tool_calls} tool calls"
            f" across {total_sessions} sessions."
        )

    # Prompt complexity
    avg_prompt_words = normalized.get("avgPromptWordCount", 0)
    if avg_prompt_words > 30:
        print(
            f"        Reference-rich prompting detected (avg {int(avg_prompt_words)} words/prompt)."
        )

    # Planning signals
    total_plans = summary.get("total_plans", 0)
    if total_plans >= 3:
        print(f"        Planning-oriented workflow — {total_plans} architecture plans found.")


def _is_active_day(entry: dict) -> bool:
    """A day counts as active only with real activity — sessions or commits."""
    return bool(entry.get("sessions", 0)) or bool(entry.get("commits", 0))


def _longest_streak(activity_by_day: list[dict]) -> int:
    """Compute the longest consecutive active-day streak from activityByDay.

    The day list spans the full date range (heatmap cells), so zero-activity
    padding days must not count toward a streak.
    """
    if not activity_by_day:
        return 0

    from datetime import date, timedelta

    dates = set()
    for entry in activity_by_day:
        d = entry.get("date")
        if d and _is_active_day(entry):
            try:
                dates.add(date.fromisoformat(d))
            except (ValueError, TypeError):
                continue

    if not dates:
        return 0

    sorted_dates = sorted(dates)
    max_streak = 1
    current_streak = 1
    for i in range(1, len(sorted_dates)):
        if sorted_dates[i] - sorted_dates[i - 1] == timedelta(days=1):
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 1
    return max_streak


def tag_ai_era(activity_by_day: list[dict], ai_era_start: str | None) -> list[dict]:
    """Tag each day ``preAi`` if it predates the first AI session, and return
    the AI-era subset.

    The default collection window is ``"all"``, so git history can reach back
    years before any AI usage; those commit-days are unioned into the durable
    activity ledger. They stay in ``activity_by_day`` (the timeline still shows
    a developer's longevity, rendered as separate "pre-AI history"), but they
    must never inflate the AI streak, active-day count, or date range. This is
    representation only — no score reads the activity surface, and
    ``aiUsageSpanDays`` is session-based.
    """
    if ai_era_start:
        for d in activity_by_day:
            d["preAi"] = bool(d.get("date") and d["date"] < ai_era_start)
    return [d for d in activity_by_day if not d.get("preAi")]


# ── Subcommand handlers ─────────────────────────────────────────────────────


def _ensure_calibrated(non_interactive: bool = False) -> dict[str, bool]:
    """Ensure consent + collection config exist. Auto-run calibrate if missing.

    Returns the enabled sources dict.
    """
    from cruise_ai.consent import (
        consented_sources,
        load_collection_config,
        load_consent,
        prompt_collection_scope,
        prompt_consent,
        save_collection_config,
        save_consent,
    )

    consent = load_consent()
    if consent is None:
        print("  No consent found. Running calibrate first...\n")
        sources = prompt_consent(non_interactive=non_interactive)
        save_consent(sources)
        consent = load_consent()

        # Also prompt for collection scope
        config = prompt_collection_scope(non_interactive=non_interactive)
        save_collection_config(config)
    else:
        # Sources added to ALL_SOURCES since the user calibrated are absent
        # from the saved consent — never silently on, never silently lost.
        from cruise_ai.consent import ALL_SOURCES, prompt_new_sources

        saved = consented_sources(consent)
        missing = [k for k in ALL_SOURCES if k not in saved]
        # A non-TTY stdin (cron, CI, piped) can never answer a prompt —
        # treat it like --yes: new sources stay off, no EOFError.
        can_prompt = not non_interactive and sys.stdin.isatty()
        if missing and can_prompt:
            sources = prompt_new_sources(missing, saved)
            save_consent(sources)
            consent = load_consent()
            if any(sources.get(k) for k in missing):
                # The cached scan predates this consent scope — drop it so
                # the newly-granted source is scanned NOW, not after cache
                # expiry (the user just said yes; the result must show it).
                from cruise_ai.paths import scan_results_path

                scan_results_path().unlink(missing_ok=True)
        elif missing:
            # Non-interactive with an existing consent: new sources stay
            # OFF for this run and are deliberately NOT persisted — writing
            # False here would disarm the mini-prompt on the next real run.
            from cruise_ai.paths import cli_invocation

            print(
                f"  New data source(s) available: {', '.join(missing)} — not"
                f" scanned until you consent. Run"
                f" `{cli_invocation()} assess` without --yes to answer just"
                f" the new question, or `{cli_invocation()} calibrate` to"
                f" review all sources."
            )
            consent = dict(consent)
            consent["sources"] = {**saved, **{k: False for k in missing}}

        # Ensure collection config exists (may be missing from older installs)
        if load_collection_config() is None:
            from cruise_ai.consent import default_collection_config

            save_collection_config(default_collection_config())

    return consented_sources(consent or {})


def cmd_recommend(args) -> None:
    """Show personalized recommendations from usage patterns."""
    import json as _json
    from cruise_ai.paths import scan_results_path, profile_path
    from cruise_ai.recommendations.engine import recommend, CONFIDENCE_THRESHOLD

    min_conf = getattr(args, "min_confidence", 60)
    filter_cat = getattr(args, "category", None)
    as_json = getattr(args, "json", False)

    # Load sessions from scan results
    sessions: list = []
    profile: dict = {}
    scan_results: dict = {}

    sr_path = scan_results_path()
    if sr_path.exists():
        try:
            scan_results = _json.loads(sr_path.read_text())
        except Exception:
            pass

    pf_path = profile_path()
    if pf_path.exists():
        try:
            profile = _json.loads(pf_path.read_text())
        except Exception:
            pass

    # Get raw sessions from adapters (if available)
    try:
        from cruise_ai.scanner import run_adapters
        from cruise_ai.consent import load_consent
        from cruise_ai.adapters._registry import default_enabled_sources
        enabled = load_consent()
        sessions, _, _ = run_adapters(None, enabled, None)
    except Exception:
        sessions = []

    if not sessions and not profile:
        print("\n  No data found. Run `cruise-ai assess` first.\n")
        return

    recs = recommend(sessions, profile, scan_results)

    # Filter by category
    if filter_cat:
        recs = [r for r in recs if r.category == filter_cat]

    # Filter by confidence
    recs = [r for r in recs if r.confidence >= min_conf]

    if as_json:
        import dataclasses
        print(_json.dumps([dataclasses.asdict(r) for r in recs], indent=2))
        return

    if not recs:
        print("\n  No recommendations found. Try running `cruise-ai assess` first.\n")
        return

    print(f"\n  ── cruise-ai recommendations ({len(recs)} found) ──\n")
    priority_icons = {"high": "🔴", "medium": "🟡", "low": "🟢"}

    for i, rec in enumerate(recs, 1):
        icon = priority_icons.get(rec.priority, "⚪")
        category_label = rec.category.replace("_", " ").title()
        print(f"  {icon} [{i}] {rec.headline}")
        print(f"       Category: {category_label} | Confidence: {rec.confidence}%")
        print(f"       {rec.detail}")
        if rec.savings_estimate:
            tokens = rec.savings_estimate.get("tokens", 0)
            cost = rec.savings_estimate.get("cost_usd", 0)
            if tokens:
                print(f"       💾 Est. savings: {tokens:,} tokens/period")
            if cost:
                print(f"       💰 Est. cost saved: ${cost:.2f}")
        print()

    print(f"  Run `cruise-ai teach` to learn how to act on any recommendation.")
    print()


def cmd_dashboard(args) -> None:
    """Show AI usage analytics dashboard."""
    import json as _json
    from cruise_ai.paths import scan_results_path, profile_path
    from cruise_ai.recommendations.analytics import dashboard

    as_json = getattr(args, "json", False)

    sessions: list = []
    profile: dict = {}

    pf_path = profile_path()
    if pf_path.exists():
        try:
            profile = _json.loads(pf_path.read_text())
        except Exception:
            pass

    try:
        from cruise_ai.scanner import run_adapters
        from cruise_ai.consent import load_consent
        enabled = load_consent()
        sessions, _, _ = run_adapters(None, enabled, None)
    except Exception:
        sessions = []

    if not sessions and not profile:
        print("\n  No data found. Run `cruise-ai assess` first.\n")
        return

    data = dashboard(sessions, profile)

    if as_json:
        print(_json.dumps(data, indent=2))
        return

    u = data["usage"]
    cost = data["cost"]
    models = data["models"]
    projects = data["projects"]
    tools = data["tools"]

    print("\n  ── cruise-ai dashboard ──\n")
    print(f"  📊 Usage")
    print(f"     Sessions:       {u['total_sessions']:>8,}")
    print(f"     Prompts:        {u['total_prompts']:>8,}")
    print(f"     Responses:      {u['total_responses']:>8,}")
    print(f"     Tokens (est.):  {u['total_tokens_estimated']:>8,}")
    print(f"     Avg prompt len: {u['avg_prompt_words']:>8} words")
    print()
    print(f"  💰 Cost Estimate")
    print(f"     Total: ~${cost['total_estimated_cost_usd']:.2f}")
    if cost.get("by_model"):
        for model, cost_val in sorted(cost["by_model"].items(), key=lambda x: -x[1])[:3]:
            print(f"     {model}: ~${cost_val:.2f}")
    print()
    if models:
        print(f"  🤖 Models")
        for model, count in sorted(models.items(), key=lambda x: -x[1])[:5]:
            print(f"     {model}: {count} sessions")
        print()
    if tools:
        print(f"  🔧 AI Tools")
        for tool, count in sorted(tools.items(), key=lambda x: -x[1])[:5]:
            print(f"     {tool}: {count} sessions")
        print()
    if projects:
        print(f"  📁 Top Projects")
        for proj, count in sorted(projects.items(), key=lambda x: -x[1])[:5]:
            print(f"     {proj}: {count} sessions")
        print()


def cmd_teach(args) -> None:
    """Show step-by-step tutorials for AI productivity patterns."""
    topic = getattr(args, "topic", None)

    tutorials = {
        "plan_mode": (
            "Plan Mode\n"
            "─────────\n"
            "Ask the AI to outline steps before executing.\n\n"
            "Usage:\n"
            "  Kiro:         /plan  or 'Plan first:'\n"
            "  Claude Code:  'Think step by step' or 'Plan before acting'\n"
            "  Cursor:       'Outline the approach first'\n\n"
            "When to use:\n"
            "  ✓ Multi-file refactors    ✓ Architecture changes\n"
            "  ✓ Complex features        ✓ When you want to review first\n\n"
            "Result: Fewer correction cycles, fewer wasted tokens."
        ),
        "subagents": (
            "Subagent Delegation\n"
            "───────────────────\n"
            "Run independent tasks in parallel.\n\n"
            "Usage:\n"
            "  Kiro:         subagent tool or pipeline stages\n"
            "  Claude Code:  Task / dispatch tool\n\n"
            "Good delegation targets:\n"
            "  ✓ Writing tests    ✓ Updating docs    ✓ Running linters\n"
            "  ✓ Generating fixtures   ✓ Security review\n\n"
            "Key: delegate tasks that don't need your input."
        ),
        "context_engineering": (
            "Context Engineering\n"
            "───────────────────\n"
            "Make the AI load your context automatically.\n\n"
            "Files by tool:\n"
            "  Kiro:         .kiro/steering/*.md\n"
            "  Kiro Skills:  .kiro/skills/*/SKILL.md\n"
            "  Claude Code:  CLAUDE.md\n"
            "  Cursor:       .cursorrules\n"
            "  Any:          AGENTS.md\n\n"
            "What to include:\n"
            "  ✓ Architecture decisions    ✓ Coding standards\n"
            "  ✓ Key file locations        ✓ Domain terminology\n"
            "  ✓ Test patterns             ✓ Project-specific patterns"
        ),
        "skills": (
            "Kiro Skills\n"
            "───────────\n"
            "Reusable instruction sets that encode workflows.\n\n"
            "Structure: .kiro/skills/<name>/SKILL.md\n\n"
            "A Skill file contains:\n"
            "  - When to use (triggers)\n"
            "  - Step-by-step instructions\n"
            "  - Tool usage patterns\n"
            "  - Output expectations\n\n"
            "Generate one: `cruise-ai recommend` → look for 'create_skill' actions."
        ),
    }

    if not topic:
        print("\n  ── cruise-ai teach ──\n")
        print("  Available topics:\n")
        for t in tutorials:
            print(f"    cruise-ai teach {t}")
        print()
        print("  Or run `cruise-ai recommend` to get personalized suggestions.")
        print()
        return

    if topic not in tutorials:
        from difflib import get_close_matches
        close = get_close_matches(topic, tutorials.keys(), n=1, cutoff=0.5)
        if close:
            print(f"\n  Unknown topic '{topic}'. Did you mean '{close[0]}'?\n")
        else:
            print(f"\n  Unknown topic '{topic}'. Run `cruise-ai teach` to see available topics.\n")
        return

    print(f"\n  ── cruise-ai teach: {topic} ──\n")
    for line in tutorials[topic].split("\n"):
        print(f"  {line}")
    print()


def cmd_feedback(args) -> None:
    """Record or view feedback on recommendations."""
    import json as _json
    from cruise_ai.recommendations.feedback import record_feedback, get_feedback_summary

    if getattr(args, "summary", False):
        summary = get_feedback_summary()
        if summary["total"] == 0:
            print("\n  No feedback recorded yet.")
            print("  Use `cruise-ai feedback acted --action-type <type>` after acting on a recommendation.\n")
            return

        print(f"\n  ── cruise-ai feedback summary ({summary['total']} entries) ──\n")
        print("  By response:")
        for resp, count in summary["by_response"].items():
            print(f"    {resp}: {count}")
        print("\n  By category:")
        for cat, responses in summary["by_category"].items():
            print(f"    {cat}: {responses}")
        print()
        return

    response = getattr(args, "response", None)
    action_type = getattr(args, "action_type", None)

    if not response:
        print("\n  Usage:")
        print("    cruise-ai feedback acted --action-type compress_prompts")
        print("    cruise-ai feedback dismissed --action-type model_routing")
        print("    cruise-ai feedback --summary")
        print()
        return

    if not action_type:
        print("\n  Please specify --action-type (the recommendation you're providing feedback on).")
        print("  Run `cruise-ai recommend --json` to see action_types.\n")
        return

    entry = record_feedback(action_type=action_type, category="", response=response)
    print(f"\n  ✓ Feedback recorded: {response} → {action_type}")
    print(f"    This will adjust future recommendation confidence.\n")


def cmd_calibrate(args) -> None:
    """Onboarding: privacy disclosure, per-source consent, collection scope."""
    from cruise_ai import cliui
    from cruise_ai.consent import (
        consented_sources,
        load_consent,
        prompt_collection_scope,
        prompt_consent,
        save_collection_config,
        save_consent,
    )
    from cruise_ai.paths import collection_config_path, consent_path

    non_interactive = getattr(args, "yes", False)

    print()
    print(cliui.intro("calibrate", "consent + collection scope — you choose what is read"))
    print()

    prior = load_consent()
    before = consented_sources(prior) if prior else {}

    # Per-source consent
    sources = prompt_consent(non_interactive=non_interactive)
    save_consent(sources)

    # Collection scope
    config = prompt_collection_scope(non_interactive=non_interactive)
    save_collection_config(config)

    print(f"  Consent written to:    {consent_path()}")
    print(f"  Config written to:     {collection_config_path()}")
    print()
    # A consent change makes the saved assessment stale — say so
    # explicitly, with exactly what changed (core rule: inputs changed →
    # dependent numbers must be recomputed)
    added = sorted(k for k, v in sources.items() if v and not before.get(k, False))
    removed = sorted(k for k, v in sources.items() if not v and before.get(k, False))
    if before and (added or removed):
        if added:
            # A widened scope can never be served by the cached scan —
            # same rule as the new-source mini-prompt in _ensure_calibrated.
            from cruise_ai.paths import scan_results_path

            scan_results_path().unlink(missing_ok=True)
        change = []
        if added:
            change.append("added: " + ", ".join(added))
        if removed:
            change.append("removed: " + ", ".join(removed))
        print(cliui.mid(f"  Consent changed ({'; '.join(change)}) — your saved"))
        print(cliui.mid("  assessment predates this scope."))
        print(f"  Run {cliui.accent(f'`{cli_invocation()} assess --rescan`')} to recompute now.")
    else:
        print(f"  Run `{cli_invocation()} assess` to scan and score your profile.")
    print()


def _engine_matches(cached: dict) -> bool:
    """True when the cached scan was produced by THIS engine version."""
    from cruise_ai.schema import METHODOLOGY_VERSION, SCHEMA_VERSION

    eng = cached.get("engine") or {}
    return bool(
        eng.get("schema") == SCHEMA_VERSION and eng.get("methodology") == METHODOLOGY_VERSION
    )


def _scan_cache_valid(cached: dict, code_scan: bool) -> bool:
    """THE ENGINE RULE: a cached scan is reusable only if the same engine
    produced it. Any schema/methodology change invalidates the cache so
    every derived field — scores, graphs, wrapped cards, leverage,
    activity — recomputes from scratch. (Within one engine version the
    cache is safe: scoring always re-runs; only run_scan-level
    derivations live in the cache.)"""
    if not _engine_matches(cached):
        return False
    # A cached scan without code-intel can't serve an --code run
    if code_scan and not cached.get("code_intel"):
        return False
    return True


# ── Config-derived signal refresh (survives scan cache) ──────────────────


def _patch_signal(
    signals: list[dict],
    label: str,
    *,
    headline: str,
    detail: str,
    remove_if_zero: bool = False,
    add_if_missing: bool = False,
    confidence: int = 80,
    kind: str = "measured",
) -> None:
    """Update an existing Lab signal by label, or add/remove it."""
    for i, sig in enumerate(signals):
        if sig.get("label") == label:
            if remove_if_zero:
                signals.pop(i)
            else:
                sig["headline"] = headline
                sig["detail"] = detail
            return
    if add_if_missing and not remove_if_zero:
        signals.append(
            {
                "label": label,
                "headline": headline,
                "detail": detail,
                "confidence": confidence,
                "kind": kind,
            }
        )


def _refresh_config_signals(scan_results: dict, enabled_sources: dict) -> None:
    """Re-read config-derived Lab signals so they stay fresh even from cache.

    Session-derived signals (delegation funnel, prompt evolution, etc.) are
    unchanged — they come from the scan.  Config-level data (MCP configs,
    git harness, tool inventory) is re-read from the live filesystem every
    run, keeping the Lab honest regardless of cache age.
    """
    from cruise_ai.scanner import HOME, count_mcp_servers

    normalized = scan_results.get("normalized", {})
    git_data = scan_results.get("git")
    experimental = scan_results.get("experimental") or {}
    signals = experimental.get("signals", [])

    # ── 1. MCP server count (from live config files) ──
    mcp_count, _ = count_mcp_servers(
        HOME,
        (git_data or {}).get("projects", []),
        cursor_enabled=bool(enabled_sources.get("cursor")),
        desktop_servers=(scan_results.get("claude_desktop") or {}).get("mcpServers"),
    )
    normalized["mcpServerCount"] = mcp_count
    mcp_calls = normalized.get("mcpToolCalls", 0)
    _patch_signal(
        signals,
        "MCP integrations",
        headline=f"{mcp_count} server{'s' if mcp_count != 1 else ''}",
        detail=f"{mcp_count} MCP servers configured, {mcp_calls} tool calls observed.",
        add_if_missing=mcp_count > 0,
        remove_if_zero=mcp_count == 0,
    )

    # ── 2. Claude Desktop MCPs (re-read config) ──
    desktop_data = scan_results.get("claude_desktop")
    if desktop_data:
        from cruise_ai.adapters.claude_desktop import default_desktop_dir

        config_file = default_desktop_dir() / "claude_desktop_config.json"
        desktop_servers: list[str] = []
        if config_file.is_file():
            try:
                cfg = json.loads(config_file.read_text())
                servers = cfg.get("mcpServers")
                if isinstance(servers, dict):
                    desktop_servers = sorted(servers.keys())
            except (json.JSONDecodeError, OSError):
                pass
        desktop_data["mcpServers"] = desktop_servers
        desktop_data["mcpServerCount"] = len(desktop_servers)

        _patch_signal(
            signals,
            "Claude Desktop MCPs",
            headline=f"{len(desktop_servers)} server{'s' if len(desktop_servers) != 1 else ''}",
            detail=(
                f"MCP servers configured in Claude Desktop: "
                f"{', '.join(desktop_servers[:6])}. "
                "Low-fidelity source: install + config only."
            ),
            add_if_missing=len(desktop_servers) > 0,
            remove_if_zero=len(desktop_servers) == 0,
            confidence=40,
            kind="estimate",
        )

    # ── 3. Git tool inventory (harness, scaffolding, deploy, automations) ──
    if git_data and git_data.get("projects"):
        from cruise_ai.aggregator import build_harness_summary

        harness = build_harness_summary(git_data, [])

        # Harness inventory
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
            _patch_signal(
                signals,
                "Harness inventory",
                headline=", ".join(inv_parts[:3]),
                detail=(
                    f"Agent tooling across your repos: {', '.join(inv_parts)}."
                    f"{md_note} This is the craft of making agents start warm — "
                    "skills, subagents, commands, and hooks are reusable leverage."
                ),
            )
        elif harness["claudeMdRepos"]:
            _patch_signal(
                signals,
                "Harness inventory",
                headline=f"CLAUDE.md x {harness['claudeMdRepos']}",
                detail=(
                    f"CLAUDE.md in {harness['claudeMdRepos']} repos "
                    f"({harness['claudeMdLines']} lines total) — context files are "
                    "the first rung; skills, custom agents, and hooks are the next."
                ),
                confidence=75,
            )

        # Context scaffolding / tension + deploy + automations
        context_tools: set[str] = set()
        scaffold_repos = 0
        deploy_tools: set[str] = set()
        automation_tools: set[str] = set()
        n_repos = len(git_data["projects"])
        for proj in git_data["projects"]:
            tools = proj.get("tools", [])
            if any(t in tools for t in ("CLAUDE.md", "Cursor Rules", "Cline Rules")):
                scaffold_repos += 1
            for tool in tools:
                if tool in ("CLAUDE.md", "Cursor Rules", "Cline Rules", "MCP"):
                    context_tools.add(tool)
                if tool in (
                    "Docker",
                    "Docker Compose",
                    "Vercel",
                    "Fly.io",
                    "Netlify",
                    "Render",
                ):
                    deploy_tools.add(tool)
                if tool in ("GitHub Actions", "GitLab CI", "pre-commit"):
                    automation_tools.add(tool)

        if deploy_tools:
            _patch_signal(
                signals,
                "Deploy readiness",
                headline=", ".join(sorted(deploy_tools)),
                detail=f"Deploy infrastructure detected: {', '.join(sorted(deploy_tools))}.",
                add_if_missing=True,
            )
        if automation_tools:
            _patch_signal(
                signals,
                "Automations",
                headline=", ".join(sorted(automation_tools)),
                detail=f"CI/automation configs found: {', '.join(sorted(automation_tools))}.",
                add_if_missing=True,
            )

        # Context scaffolding / tension
        ref_rate = normalized.get("referenceUsageRate")
        if n_repos >= 3 and ref_rate is not None:
            if scaffold_repos == 0 and ref_rate >= 0.4:
                _patch_signal(
                    signals,
                    "Context tension",
                    headline="reference-rich, scaffold-free",
                    detail=(
                        f"{round(ref_rate * 100)}% reference-rich prompting but no "
                        f"CLAUDE.md/rules files in {n_repos} repos — you carry "
                        "context by hand each session. A context file would "
                        "bank what you keep retyping."
                    ),
                    confidence=65,
                    add_if_missing=True,
                )
            elif scaffold_repos > 0:
                pct_repos = round(100 * scaffold_repos / n_repos)
                _patch_signal(
                    signals,
                    "Context scaffolding",
                    headline=f"{scaffold_repos} of {n_repos} repos ({pct_repos}%)",
                    detail=(
                        f"Repos with agent context files ({', '.join(sorted(context_tools))}). "
                        "Scaffolded repos let agents start warm; the unscaffolded "
                        "ones are the cheapest leverage still on the table."
                    ),
                    confidence=75,
                    add_if_missing=True,
                )

    if signals:
        experimental["available"] = True


def cmd_assess(args, *, _show_intro: bool = True) -> None:
    """Scan + score + write assessment JSON + honest progress."""
    from cruise_ai.paths import data_dir as _data_dir
    from cruise_ai.paths import profile_path as _profile_path
    from cruise_ai.paths import scan_results_path as _scan_results_path

    _data_dir()  # ensure directory exists
    scan_results_file = _scan_results_path()
    profile_file = _profile_path()

    non_interactive = getattr(args, "yes", False)
    rescan = getattr(args, "rescan", False)
    project = getattr(args, "project", None)
    code_scan = getattr(args, "code", False)

    # Consent gate
    enabled = _ensure_calibrated(non_interactive=non_interactive)

    from cruise_ai import cliui

    if _show_intro:
        print()
        print(
            cliui.intro(
                "assess",
                "scan + score locally — one assessment JSON",
                "your consented sources: sessions, git, durable ledger",
            )
        )
    print()

    # Step 1: Scan
    print(cliui.step(1, 3, "Scanning local AI coding sessions + git..."))

    # --project narrows the scan: validate the path and never serve the
    # cached all-projects scan for it
    if project:
        proj_path = Path(os.path.expanduser(project))
        if not proj_path.is_dir():
            print(f"  Error: project path not found: {project}")
            return

    scan_results = None
    use_cache = not rescan and not project
    if use_cache and scan_results_file.is_file():
        mtime = scan_results_file.stat().st_mtime
        if time.time() - mtime < 3600:
            with open(scan_results_file) as f:
                cached = json.load(f)
            if _scan_cache_valid(cached, code_scan):
                scan_results = cached
                print("        Using cached scan (< 1 hour old)")
                print("        Use --rescan to force refresh")
            elif not _engine_matches(cached):
                print("        Engine updated since the cached scan —")
                print("        recomputing everything from scratch.")

    if scan_results is None:
        from cruise_ai.consent import load_collection_config

        collection_config = load_collection_config()
        if code_scan:
            print("        Code scan enabled: repo files read locally,")
            print("        reduced to metrics only (never stored, never sent)")
        scan_results = run_scan(
            project_filter=project,
            enabled_sources=enabled,
            collection_config=collection_config,
            code_scan=code_scan,
        )
        with open(scan_results_file, "w") as f:
            json.dump(scan_results, f, indent=2, default=str)

    # Config-derived Lab signals: always re-read from live config files
    # so MCP counts, harness inventory, etc. stay fresh even from cache.
    _refresh_config_signals(scan_results, enabled)

    # Honest progress
    _print_signal_insights(scan_results)
    print()

    # Step 2: Score
    print(cliui.step(2, 3, "Scoring profile..."))
    from cruise_ai.aggregator import build_summary_line
    from cruise_ai.profile_data import _build_default_profile, save_profile
    from cruise_ai.schema import SCHEMA_VERSION
    from cruise_ai.scoring import score_profile

    scored = score_profile(scan_results)

    tools_found = scan_results.get("tools_detected", [])
    summary = scan_results.get("summary", {})

    # Merge scoring output with identity + scan summary data
    full_profile = _build_default_profile()
    full_profile.update(scored)
    full_profile["schema_version"] = SCHEMA_VERSION
    full_profile["intent_score"] = scored.get("composite", 0)
    full_profile["tools_detected"] = tools_found
    _sc = (scan_results.get("cursor") or {}).get("scored_commits") or {}
    full_profile["signals"] = {
        "ai_code_blocks": summary.get("total_ai_blocks", 0),
        "ai_lines_survived": _sc.get("totalAiLines", 0),
        "scored_commits": summary.get("total_scored_commits", 0),
        "architecture_plans": summary.get("total_plans", 0),
        "models_used": summary.get("models_used", []),
    }
    full_profile["verification"] = {
        "source": tools_found[0] if tools_found else "unknown",
        "verified": len(tools_found) > 0,
    }

    # Wrapped "tools" card: the AI surfaces actually detected, plus any CLI AI tools
    wrapped = full_profile.get("wrappedStats")
    if isinstance(wrapped, dict):
        cli_tools = wrapped.get("tools") or []
        surfaces = {
            "claude_code": "Claude Code",
            "cursor_ide": "Cursor",
            "codex_cli": "Codex CLI",
            "kiro": "Kiro",
            "aider": "Aider",
            "cline": "Cline",
            "continue": "Continue.dev",
            "copilot_chat": "Copilot Chat",
            "windsurf": "Windsurf",
            "zed_ai": "Zed AI",
            "jetbrains_ai": "JetBrains AI",
            "cody": "Cody",
        }
        detected = [surfaces.get(t, t) for t in tools_found]
        wrapped["tools"] = detected + [t for t in cli_tools if t not in detected]

    # Assessment metadata + confidence
    from cruise_ai.scanner import iso_now as _iso_now
    from cruise_ai.schema import TAXONOMY_VERSION

    normalized = scan_results.get("normalized", {})
    total_sessions = summary.get("total_sessions", 0)

    # Per-dimension sufficiency: a score from a tiny sample is flagged provisional
    # (the score itself is unchanged) — feeds the confidence depth factor + the UI
    # "small sample" tag.
    from cruise_ai.aggregator import mark_dimension_sufficiency

    mark_dimension_sufficiency(
        full_profile.get("dimensions") or {}, normalized, full_profile.get("signals") or {}
    )

    # Build date range string — AI era only (pre-AI git history is excluded
    # from the headline range; it stays in activityByDay tagged preAi).
    activity_days = scan_results.get("activityByDay", [])
    ai_era_days = [d for d in activity_days if not d.get("preAi")]
    if ai_era_days:
        dates = [d["date"] for d in ai_era_days if d.get("date")]
        if dates:
            date_range = f"{dates[0]} to {dates[-1]}"
        else:
            date_range = "unknown"
    else:
        date_range = "unknown"

    # Map tool IDs to display names
    _tool_labels = {
        "claude_code": "Claude Code",
        "cursor_ide": "Cursor IDE",
        "codex_cli": "Codex CLI",
        "kiro": "Kiro",
        "aider": "Aider",
        "cline": "Cline",
        "continue": "Continue.dev",
        "copilot_chat": "Copilot Chat",
        "windsurf": "Windsurf",
        "zed_ai": "Zed AI",
        "jetbrains_ai": "JetBrains AI",
        "cody": "Cody",
    }
    sources_used = [_tool_labels.get(t, t) for t in tools_found]
    if scan_results.get("git"):
        sources_used.append("git")

    # Per-tool fidelity detail for Provenance — each adapter declares
    # what it could honestly read (deep / counts / presence)
    _other = scan_results.get("otherTools") or {}
    tools_detail = []
    for tid, payload in sorted(_other.items()):
        tools_detail.append(
            {
                "id": tid,
                "label": payload.get("label") or _tool_labels.get(tid, tid),
                "fidelity": payload.get("fidelity", "counts"),
                "note": payload.get("note", ""),
            }
        )
    _cd = scan_results.get("claude_desktop")
    if _cd:
        tools_detail.append(
            {
                "id": "claude_desktop",
                "label": "Claude Desktop",
                "fidelity": "presence",
                "note": _cd.get("note", "Install + MCP config only (experimental)."),
            }
        )
    _lm = scan_results.get("localModels")
    if _lm:
        for rt in _lm.get("runtimes", []):
            tools_detail.append(
                {
                    "id": rt.get("runtime"),
                    "label": rt.get("label"),
                    "fidelity": "counts",
                    "note": rt.get("note", ""),
                    "models": rt.get("models", [])[:10],
                }
            )
    full_profile["toolsDetail"] = tools_detail

    # Honest, variable confidence — five factors that reward substance, never
    # pinned. Depth (per-dimension sample sufficiency) is the biggest factor, so
    # many short sessions over a long sparse span no longer buys confidence.
    from cruise_ai.aggregator import build_confidence

    span_days = summary.get("ai_usage_span_days", 0) or 0
    _conf_active_days = len([d for d in ai_era_days if _is_active_day(d)])
    conf = build_confidence(
        normalized,
        sources_used,
        span_days,
        total_sessions,
        dims=full_profile.get("dimensions") or {},
        active_hours=normalized.get("totalEstimatedHours", 0) or 0,
        active_days=_conf_active_days,
        code_scan_ran=bool(scan_results.get("code_intel")),
    )
    confidence = conf["score"]

    from cruise_ai.schema import METHODOLOGY_VERSION as _METHODOLOGY_VERSION

    full_profile["assessment"] = {
        "schema_version": SCHEMA_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "methodology_version": _METHODOLOGY_VERSION,
        "generated_at": _iso_now(),
        "sources_used": sources_used,
        "sessions": total_sessions,
        "dateRange": date_range,
        "privacyMode": "local-only",
        "confidence": confidence,
        "confidenceFactors": conf["factors"],
    }

    # Enrichment slot — check if previously ingested, else heuristic fallback
    from cruise_ai.enrichment import build_heuristic_enrichment

    existing_profile_path = _profile_path()
    existing_enrichment = None
    if existing_profile_path.exists():
        try:
            with open(existing_profile_path) as _ef:
                _existing = json.load(_ef)
                existing_enrichment = _existing.get("enrichment")
        except (json.JSONDecodeError, OSError):
            pass

    if (
        isinstance(existing_enrichment, dict)
        and existing_enrichment.get("source", "agent") == "agent"
    ):
        # Preserve user-submitted (agent) enrichment across rescans;
        # heuristic text is rebuilt from the fresh scores instead.
        full_profile["enrichment"] = existing_enrichment
    else:
        # Heuristic fallback (derived from scored data)
        full_profile["enrichment"] = build_heuristic_enrichment(full_profile)

    # Experimental signals (never shareable)
    full_profile["experimental"] = scan_results.get(
        "experimental",
        {
            "available": False,
            "signals": [],
            "codeIntelligence": [],
        },
    )

    # Coverage report — what wasn't collected + the knob to widen it.
    # Private: provenance/Details only, excluded from shareable (allowlist).
    full_profile["coverage"] = scan_results.get("coverage", {})

    # Structured activity summary — AI era only (sessions + AI-era commits);
    # pre-AI git days stay in `days` tagged preAi but don't inflate the totals.
    _ai_era_days = [d for d in activity_days if not d.get("preAi")]
    streak = max(normalized.get("longestStreakDays", 0) or 0, _longest_streak(_ai_era_days))
    active_days_count = len([d for d in _ai_era_days if _is_active_day(d)])
    avg_session_hours = normalized.get("totalEstimatedHours", 0)
    if total_sessions > 0:
        avg_session_hours = round(avg_session_hours / total_sessions, 1)
    full_profile["activity"] = {
        "streak": streak,
        "activeDays": active_days_count,
        "avgSessionHours": avg_session_hours,
        "totalSessions": total_sessions,
        "days": activity_days,
    }

    # Front-end view data
    full_profile["summaryLine"] = build_summary_line(
        scored.get("workMode"),
        scored.get("dimensions"),
        scan_results.get("normalized"),
    )
    full_profile["activityByDay"] = scan_results.get("activityByDay", [])
    full_profile["harness"] = scan_results.get("harness", {})

    # Daily metrics snapshot — honest longitudinal you-vs-you data
    from cruise_ai.history import append_snapshot

    _norm = scan_results.get("normalized", {})
    append_snapshot(
        {
            "composite": full_profile.get("composite"),
            "confidence": confidence,
            "sessions": total_sessions,
            "subagentDispatches": _norm.get("subagentDispatches", 0),
            "maxParallelAgents": _norm.get("maxParallelAgents", 0),
            "avgPromptWords": _norm.get("avgPromptWords", 0),
            "planModePercent": _norm.get("planModePercent", 0),
            "scaffoldedRepos": full_profile.get("harness", {}).get("scaffoldedRepos", 0),
            "leverageMode": (full_profile.get("positioning", {}).get("leverageMode") or {}).get(
                "current"
            ),
        }
    )
    full_profile["scannedProjects"] = scan_results.get("projects", [])
    full_profile["stackSummary"] = scan_results.get("stack", {})
    full_profile["modelsSummary"] = scan_results.get("models", {})
    full_profile["leverage"] = scan_results.get("leverage")

    # Multi-device union (local mirror of synced snapshots; no network).
    # Activity calendar + provenance only — scores stay per-device.
    from cruise_ai.sync_merge import apply_multi_device

    apply_multi_device(full_profile)
    save_profile(full_profile)

    composite = full_profile.get("intent_score", 0)
    primary_title = full_profile.get("primaryTitle", {})
    title_name = primary_title.get("name", "") if primary_title else ""

    print(f"        Intent Score: {cliui.bold(str(composite))}", end="")
    if title_name:
        print(f" | Primary: {cliui.accent(title_name)}")
    else:
        print()
    print()

    # Step 3: Print summary
    print(cliui.step(3, 3, "Profile Summary"))
    print("  " + ("─" if cliui.color_enabled() else "-") * 42)

    dims = full_profile.get("dimensions", {})
    archetypes = full_profile.get("archetypes", [])
    anti_patterns = full_profile.get("antiPatterns", [])
    trajectory = full_profile.get("trajectory", {})

    # Dimensions
    print()
    print("  Dimensions:")
    for key, val in dims.items():
        score = val.get("score", val) if isinstance(val, dict) else val
        if not isinstance(score, (int, float)):
            score = 0
        score = int(score)
        label = key.replace("_", " ").title()
        print(f"    {label:25s} [{cliui.bar(score)}] {cliui.score_text(score)}")

    # Top archetypes
    if archetypes:
        print()
        print("  Top Archetypes:")
        for a in archetypes[:5]:
            lvl = a.get("level", {}).get("label", "-")
            sc = a.get("score", 0)
            print(
                f"    {a.get('icon', '?')} {a['name']:25s} "
                f"{cliui.band(sc)(f'{sc:3d}')}  {cliui.dim(f'({lvl})')}"
            )

    # Primary title
    if primary_title:
        emoji = primary_title.get("emoji", "")
        name = primary_title.get("name", "")
        legendary = " [LEGENDARY]" if primary_title.get("legendary") else ""
        print(f"\n  Primary Title: {emoji} {name}{legendary}")

    # Anti-patterns
    if anti_patterns:
        print(f"\n  Risk Signals: {len(anti_patterns)} detected")
        for p in anti_patterns:
            print(f"    {p.get('icon', '!')} {p['name']}")

    # Trajectory
    if trajectory and trajectory.get("id") != "insufficient":
        print(f"\n  Trajectory: {trajectory.get('label', '-')}")

    # Coverage: what exists here that wasn't collected + the knob to widen
    coverage = full_profile.get("coverage") or {}
    gaps = coverage.get("gaps") or []
    print()
    if gaps:
        print(
            f"  Coverage: {len(gaps)} way{'s' if len(gaps) != 1 else ''} to widen this assessment"
        )
        for gap in gaps:
            print(f"    - {gap['gap']}")
            print(f"      {cliui.dim('widen: ' + gap['widen'])}")
    else:
        print("  Coverage: maximal — every detected source was collected.")

    print()
    print(cliui.dim(f"  Assessment saved to: {profile_file}"))
    print(cliui.dim(f"  Scan data saved to:  {scan_results_file}"))
    print()
    print(f"  Run {cliui.accent(f'`{cli_invocation()} report`')} to view in your browser.")

    # Nudge toward enrich when narrative is still heuristic
    _enr = full_profile.get("enrichment") or {}
    if _enr.get("source") != "agent":
        print(
            f"  {cliui.dim('Enrich your profile:')} "
            f"{cliui.accent(f'`{cli_invocation()} enrich`')} "
            f"{cliui.dim('adds richer narrative to your report.')}"
        )
    print()


def _existing_profile_notice() -> str | None:
    """A one-paragraph notice when a profile already exists on this machine.

    State lives in ``~/.cruise_ai/`` — independent of the repo clone —
    so a fresh clone still shows the previous profile. Surfacing the build
    date makes that explicit instead of looking like stale data, and points
    at the two ways to change it (rescan / reset)."""
    from cruise_ai.paths import profile_path

    p = profile_path()
    if not p.is_file():
        return None
    try:
        with open(p) as f:
            prof = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    meta = prof.get("assessment") or {}
    when = meta.get("generated_at")
    sessions = meta.get("sessions")

    when_label = "earlier"
    if isinstance(when, str):
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
            when_label = dt.astimezone().strftime("%b %d, %Y at %H:%M")
        except Exception:
            when_label = when

    lines = [
        f"  You already have a profile on this machine (built {when_label}"
        + (f", {sessions} sessions).".rstrip() if isinstance(sessions, int) else ")."),
        "  It lives in ~/.cruise_ai/ — shared across every clone, so this",
        "  is your existing profile, not a fresh scan of this folder.",
        f"  Rebuild from your latest data: {cli_invocation()} assess --rescan",
        f"  Wipe everything and start over: {cli_invocation()} reset",
    ]
    return "\n".join(lines)


def cmd_start(args) -> None:
    """The whole pipeline, one command: consent gate on first run,
    assess (cache-aware unless --rescan), then serve both views.
    Each step prints its own intro — start only sequences them."""
    from cruise_ai import cliui

    print()
    print(
        cliui.intro(
            "start",
            "the whole pipeline: calibrate (first run) + assess + report",
            "stops at the privacy line — nothing leaves this machine",
        )
    )

    # If a profile already exists, say so plainly — state persists in
    # ~/.cruise_ai/ across clones, which otherwise looks like stale data.
    if not getattr(args, "rescan", False):
        notice = _existing_profile_notice()
        if notice:
            print()
            print(notice)

    cmd_assess(args, _show_intro=False)
    cmd_report(args)


def cmd_report(args) -> None:
    """Start the local profile server."""
    requested_port = getattr(args, "port", 7749) or 7749
    # Live mode is DEFERRED POST-LAUNCH and hidden — the file-watcher is not
    # shipped yet. Force it off here regardless of the (hidden) --live flag so
    # the watch-path discovery below and the watcher in hub.run_server stay
    # inert. Restore `getattr(args, "live", False)` when live mode is ready.
    live = False
    demo = getattr(args, "demo", False)

    from cruise_ai.paths import profile_path

    if demo:
        from cruise_ai.paths import PACKAGE_DIR

        example = PACKAGE_DIR / "examples" / "profile.json"
        os.environ["CRUISE_AI_PROFILE_PATH"] = str(example)
        print("  Demo mode: serving the bundled example profile.")
        print("  Your own data is untouched.")
    elif not profile_path().is_file():
        print("  No assessment found. Running assess first...\n")
        cmd_assess(args)

    # Auto-pick a free port: another instance on 7749 should never
    # block a fresh `report`
    from cruise_ai import hub

    port = hub.pick_port(requested_port)
    if port != requested_port:
        print(f"  Port {requested_port} is busy — using {port} instead.")

    from cruise_ai import cliui as _rui

    print()
    print(
        _rui.intro(
            "report",
            "serve the profile + report views on localhost",
            "profile.json only — no rescan unless you ask",
        )
    )
    print()
    print(f"  Starting profile server on port {port}...")
    print(f"  Profile: http://localhost:{port}/profile")
    print(f"  Report:  http://localhost:{port}/report")
    if live:
        from cruise_ai.live import discover_watch_paths

        watch = discover_watch_paths()
        if watch:
            session_sources = [sid for sid, _ in watch if not sid.startswith("git:")]
            repo_count = len(watch) - len(session_sources)
            print(
                f"  Live:    watching {len(session_sources)} session "
                f"source{'s' if len(session_sources) != 1 else ''} + "
                f"{repo_count} repo{'s' if repo_count != 1 else ''} (local only)"
            )
        else:
            print("  Live:    no watchable sources found (~/.claude, ~/.cursor,")
            print("           ~/.codex, scanned repos) — views still offer manual refresh")
    # --live tip hidden (post-launch)
    print()
    os.environ["PORT"] = str(port)

    open_browser = (
        not getattr(args, "no_open", False)
        and not os.environ.get("CRUISE_AI_NO_BROWSER")
        and sys.stdout.isatty()
    )
    try:
        hub.run_server(port=port, live=live, open_browser=open_browser)
    except OSError as e:
        if getattr(e, "errno", None) in (48, 98):  # EADDRINUSE (mac/linux)
            print(f"  Port {port} is already in use — a profile server may")
            print(f"  already be running at http://localhost:{port}/profile")
            print(f"  Otherwise pick another port: {cli_invocation()} report --port {port + 1}")
        else:
            raise


def cmd_enrich(args) -> None:
    """AI narrative enrichment — opt-in, derived-only."""
    from cruise_ai.consent import load_collection_config
    from cruise_ai.enrichment import (
        build_enrichment_prompt,
        ingest_enrichment,
        select_excerpts,
    )
    from cruise_ai.paths import profile_path, scan_results_path

    submit_file = getattr(args, "submit", None)

    from cruise_ai import cliui as _ui

    print()
    print(
        _ui.intro(
            "enrich",
            "the story on top of the numbers — written by YOUR agent",
            "derived excerpts only (pointers, never code); can never change a score",
        )
    )

    if getattr(args, "key", None):
        print()
        print("  Note: the BYO-key path (--key) is not implemented yet — your key")
        print("  was NOT used or stored. Generating the copy-paste prompt instead,")
        print("  which runs on your own agent and needs no key at all.")

    # ── Revoke path: remove ingested narrative, restore heuristic text ──
    if getattr(args, "revoke", False):
        from cruise_ai.enrichment import revoke_enrichment

        if not profile_path().exists():
            print(f"  No assessment found. Run `{cli_invocation()} assess` first.")
            return
        success, msg = revoke_enrichment(profile_path())
        print(f"  {msg}")
        if success:
            print("  If a report tab is open, reload it (Cmd/Ctrl+R) to see the change.")
        return

    # ── Submit path: validate + ingest a result ──
    if submit_file:
        from cruise_ai.enrichment import parse_submission
        from cruise_ai.paths import data_dir

        result_path = Path(submit_file)
        if not result_path.exists():
            print(f"  Error: file not found: {submit_file}")
            return

        result, parse_err = parse_submission(result_path.read_text())
        attempts_file = data_dir() / "enrichment_attempts"
        if result is None:
            success, msg = False, f"Enrichment rejected: {parse_err}"
        else:
            success, msg = ingest_enrichment(result, profile_path())

        if success:
            attempts_file.unlink(missing_ok=True)
            print(f"  {msg}")
            print(f"  Profile updated at: {profile_path()}")
            print(f"  Revoke anytime with: {cli_invocation()} enrich --revoke")
            return

        # Rejected: re-prompt once, then fail soft to heuristic text.
        prior_attempts = 0
        if attempts_file.exists():
            try:
                prior_attempts = int(attempts_file.read_text().strip() or 0)
            except ValueError:
                prior_attempts = 0
        attempts_file.write_text(str(prior_attempts + 1))

        print(f"  {msg}")
        print()
        if prior_attempts == 0:
            print("  Re-prompt your agent ONCE with this correction, then resubmit:")
            reason = msg.removeprefix("Enrichment rejected: ")
            print(f'    "Your previous output was rejected: {reason}')
            print("     Return ONLY the JSON object — no markdown fences, no code,")
            print('     no extra keys, no ranking language."')
        else:
            print("  Second rejection — keeping the heuristic narrative instead.")
            print("  Your profile still renders fully; the scores are unaffected.")
            print(f"  You can retry later with a fresh prompt: {cli_invocation()} enrich")
            attempts_file.unlink(missing_ok=True)
        return

    # ── Generate path: produce prompt + excerpts ──
    print()
    print("  cruise_ai — Enrich")
    print("  " + "=" * 42)
    print()

    # Load profile + scan data
    p_path = profile_path()
    sr_path = scan_results_path()

    if not p_path.exists():
        print(f"  No profile found. Run `{cli_invocation()} assess` first.")
        return

    with open(p_path) as f:
        profile = json.load(f)

    scan_results_data: dict = {}
    if sr_path.is_file():
        try:
            with open(sr_path) as f:
                scan_results_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            scan_results_data = {}

    # Collect session excerpts
    non_interactive = getattr(args, "yes", False)
    enabled = _ensure_calibrated(non_interactive=non_interactive)
    collection_config = load_collection_config()

    from cruise_ai.adapters._registry import run_adapters

    sessions, _, _ = run_adapters(
        enabled_sources=enabled,
        collection_config=collection_config,
    )

    excerpts = select_excerpts(sessions)

    # Build signals summary for the prompt
    dims = profile.get("dimensions", {})
    archetypes = profile.get("archetypes", [])
    work_mode = profile.get("workMode", {})
    positioning = profile.get("positioning", {})

    signals = {
        "totalSessions": profile.get("assessment", {}).get("sessions", 0),
        "dominantWorkMode": work_mode.get("dominant", {}).get("id", ""),
        "dimensionScores": {k: v.get("score") for k, v in dims.items() if isinstance(v, dict)},
        "topArchetypes": [a.get("name", "") for a in archetypes[:3] if isinstance(a, dict)],
        "tools": profile.get("tools_detected", []),
        "primaryModel": profile.get("wrappedStats", {}).get("models", ["unknown"])[0]
        if profile.get("wrappedStats", {}).get("models")
        else "unknown",
        "composite": profile.get("composite"),
        "positioning": positioning,
        "streak": profile.get("activity", {}).get("streak", 0),
        "planModePct": profile.get("wrappedStats", {}).get("planModePercent", 0),
        # Calibration inputs (v2 prompt): integration depth + data weight
        "confidence": profile.get("assessment", {}).get("confidence", 0),
        "aiAuthorship": {
            "aiShare": (profile.get("leverage") or {}).get("aiShare"),
            "aiLines": (profile.get("leverage") or {}).get("aiLines"),
            "trackedCommits": (profile.get("leverage") or {}).get("trackedCommits"),
        }
        if profile.get("leverage")
        else None,
        "agentRuntimeHours": profile.get("wrappedStats", {}).get("agentRuntimeHours", 0),
        "subagentDispatches": profile.get("wrappedStats", {}).get("subagentDispatches", 0),
        "buildDomainDistribution": (
            (profile.get("positioning", {}).get("buildDomain") or {}).get("distribution")
        ),
    }

    dominant_mode = work_mode.get("dominant", {}).get("id", "Unknown")
    primary_arch = archetypes[0].get("name", "Unknown") if archetypes else "Unknown"

    from cruise_ai.enrichment import build_evidence_bank, prompt_file_text

    evidence_bank = build_evidence_bank(scan_results_data, profile)
    prompt = build_enrichment_prompt(signals, dominant_mode, primary_arch, excerpts, evidence_bank)

    # Save to file
    from cruise_ai.paths import data_dir

    enrichment_dir = data_dir()
    enrichment_file = enrichment_dir / "enrichment_prompt.txt"
    enrichment_file.write_text(prompt_file_text(prompt))

    print(f"  Enrichment prompt saved to: {enrichment_file}")
    print()
    print("  Next steps:")
    print("  1. Copy the prompt from the file above")
    print("  2. Paste it into your own Claude/Cursor/ChatGPT session")
    print("  3. Save the JSON response to a file (e.g. enrichment_result.json)")
    print(f"  4. Run: {cli_invocation()} enrich --submit enrichment_result.json")
    print()
    print(f"  Excerpt count: {len(excerpts)}")
    print(f"  Prompt length: {len(prompt):,} chars")
    print()


def cmd_export(args) -> None:
    """Static self-hostable artifact: redacted shareable JSON + both views."""
    from cruise_ai.export import export_static

    out = getattr(args, "out", "./cruise_ai-export")
    print()
    print("  cruise_ai — Export")
    print("  " + "=" * 42)
    print()
    try:
        summary = export_static(out)
    except RuntimeError as e:
        print(f"  {e}")
        return

    print(f"  Static artifact written to: {summary['outDir']}")
    print(f"  Files: {len(summary['files'])}")
    print(f"  Shared sections: {', '.join(summary['sections'])}")
    print()
    print("  Contents are visibility-redacted and derived-only: no raw")
    print("  prompts, no experimental signals, no hidden projects, no")
    print("  private growth data. Drop the folder on any static host, or")
    print("  preview locally:")
    print(f"    python3 -m http.server -d {summary['outDir']} 8080")
    print()


def cmd_publish(args) -> None:
    """Opt-in network publish — explicit, derived-only, revocable."""
    from cruise_ai.network import (
        DEFAULT_REGISTRY,
        build_publish_payload,
        load_publish_state,
        publish,
        registry_reachable,
    )

    registry = getattr(args, "registry", None) or DEFAULT_REGISTRY

    print()
    print("  cruise_ai — Publish (opt-in)")
    print("  " + "=" * 42)
    print()

    try:
        payload = build_publish_payload()
    except RuntimeError as e:
        print(f"  {e}")
        return

    # Preflight BEFORE the consent ceremony — never make someone type
    # 'publish' into a dead socket (dry runs skip this; nothing is sent).
    if not getattr(args, "dry_run", False) and not registry_reachable(registry):
        print(f"  Registry not reachable at {registry}.")
        print()
        print("  No hosted cruise_ai registry exists yet. Either:")
        print(f"    - start a self-hosted one:  {cli_invocation()} network serve")
        print("    - or point at another:      --registry https://your-registry")
        print()
        print("  Nothing was sent.")
        return

    state = load_publish_state()
    action = "republish (update)" if state else "publish"
    print(f"  This will {action} your curated profile to:")
    print(f"    {registry}")
    print()
    print("  Exactly these sections (visibility-filtered, derived-only):")
    for key in sorted(payload.keys()):
        print(f"    - {key}")
    print()
    print("  Never sent: raw code, transcripts, prompts, hidden projects,")
    print("  private growth, anti-patterns, experimental signals, coverage.")
    print("  Revocable anytime: cruise_ai unpublish")
    print()

    if getattr(args, "dry_run", False):
        print("  Dry run: nothing was sent.")
        print()
        return

    if not getattr(args, "confirm", False):
        answer = input("  Type 'publish' to confirm (anything else cancels): ").strip()
        if answer.lower() != "publish":
            print("  Cancelled. Nothing was sent.")
            return

    try:
        result = publish(registry)
    except RuntimeError as e:
        print(f"  {e}")
        return

    verb = "updated on" if result.get("updated") else "published to"
    print(f"  Profile {verb} the registry.")
    print(f"  Builder ID: {result['builderId']}")
    print(f"  Discovery:  {result['registry']}/v1/builders/{result['builderId']}")
    print(f"  Unpublish anytime: {cli_invocation()} unpublish")
    print()


def cmd_sync(args) -> None:
    """Multi-device sync via the USER'S OWN private git repo — explicit,
    derived-only, revocable. The outbound transport lives in network.py;
    the merge is deterministic and local (sync_merge.py)."""
    from cruise_ai import cliui as _cliui
    from cruise_ai.network import load_sync_config, sync_revoke, sync_run

    print()
    print(
        _cliui.intro(
            "sync",
            "one merged profile across your machines (opt-in)",
            "derived-only snapshots — never transcripts or code",
        )
    )
    print()

    if getattr(args, "revoke", False):
        try:
            print(f"  {sync_revoke()}")
        except RuntimeError as e:
            print(f"  {e}")
        print()
        return

    if getattr(args, "status", False):
        from cruise_ai.sync_merge import device_identity, load_device_snapshots

        cfg = load_sync_config()
        ident = device_identity()
        snaps = load_device_snapshots()
        if not cfg:
            print("  Not configured. Your profile is single-device, local-only.")
            print(f"  To opt in: {cli_invocation()} sync --repo <your PRIVATE repo>")
        else:
            print(f"  Sync repo:   {cfg['repoUrl']}")
            print(f"  This device: {ident['deviceName']} ({ident['deviceId']})")
            print(f"  Devices in local mirror: {len(snaps)}")
            for s in snaps:
                marker = " (this device)" if s.get("deviceId") == ident["deviceId"] else ""
                summary = s.get("summary") or {}
                print(
                    f"    - {s.get('deviceName')}: {summary.get('sessions', 0)} sessions, "
                    f"{summary.get('activeDays', 0)} active days{marker}"
                )
        print()
        return

    repo_url = getattr(args, "repo", None)
    cfg = load_sync_config()
    if not cfg and not repo_url:
        print("  No sync repo configured. Sync stores derived-only snapshots in a")
        print("  PRIVATE git repo YOU own (your account, revocable):")
        print(f"    {cli_invocation()} sync --repo git@github.com:YOU/cruise-ai-sync.git")
        print()
        return

    if not cfg and repo_url:
        # First-time consent ceremony — say exactly what will be synced
        print("  This will push a derived-only snapshot of THIS device to:")
        print(f"    {repo_url}")
        print()
        print("  Exactly what syncs: session IDs + per-day counts, per-repo")
        print("  commit-day counts, repo names, activity days.")
        print("  Never synced: prompts, transcripts, code, file paths, scores.")
        print("  Revocable anytime: cruise_ai sync --revoke")
        print()
        if not getattr(args, "yes", False):
            answer = input("  Type 'sync' to confirm (anything else cancels): ").strip()
            if answer.lower() != "sync":
                print("  Cancelled. Nothing was sent.")
                return

    try:
        result = sync_run(repo_url)
    except RuntimeError as e:
        print(f"  {e}")
        print()
        return

    print(f"  Synced. Devices in store: {result['devices']}")
    if result["devices"] >= 2:
        print(f"  Run `{cli_invocation()} assess --rescan` to fold the union")
        print("  into your profile (merged activity + device provenance).")
    else:
        print("  One device so far — run sync on your other machines to merge.")
    print()


def cmd_reset(args) -> None:
    """Delete local cruise_ai data and start fresh.

    A clean clone still shows the previous profile because every bit of
    state lives in ``~/.cruise_ai/`` (independent of where the repo is
    cloned). ``reset`` is the explicit, user-initiated way to forget it.

    By default it wipes ``~/.cruise_ai/data/`` — profile, scan cache,
    consent, collection scope, visibility, enrichment, AND the durable
    history ledger (included on purpose: the user asked to forget
    everything). ``--all`` also removes the rest of ``~/.cruise_ai/``
    (a self-hosted registry store + the local sync-repo clone + user
    config). All local — nothing leaves the machine.
    """
    import shutil

    from cruise_ai import cliui as _ui
    from cruise_ai.paths import data_dir, user_home

    wipe_all = getattr(args, "all", False)
    non_interactive = getattr(args, "yes", False)

    home = user_home()
    data = data_dir()

    print()
    print(
        _ui.intro(
            "reset",
            "delete local data and start fresh",
            "removes files under ~/.cruise_ai/ — nothing is sent anywhere",
        )
    )
    print()

    target = home if wipe_all else data
    if not target.exists() or not any(target.iterdir()):
        print("  Nothing to reset — no local data found.")
        print()
        return

    if wipe_all:
        print(f"  This permanently deletes EVERYTHING under:\n    {home}")
        print("  (profile, scan cache, consent, history ledger, sync clone,")
        print("   self-hosted registry store, and user config)")
    else:
        print(f"  This permanently deletes your local data under:\n    {data}")
        print("  (profile, scan cache, consent, collection scope, visibility,")
        print("   enrichment, and the durable history ledger)")
    print()

    # A still-live publish lives on the registry, not locally — a local
    # wipe can't reach it. Flag it so the user revokes it explicitly.
    # (Path computed locally; importing network.py here would trip the
    # assessment-path privacy guard.)
    if (data / "publish_state.json").is_file():
        print("  Note: you have a published profile. A reset only clears local")
        print(f"  state — revoke the registry copy first: {cli_invocation()} unpublish")
        print()

    if not non_interactive:
        answer = input("  Type 'reset' to confirm (anything else cancels): ").strip()
        if answer.lower() != "reset":
            print("  Cancelled. Nothing was deleted.")
            print()
            return

    removed = 0
    if wipe_all:
        # Remove the whole home tree, then recreate the empty root so the
        # next command has a place to write.
        for entry in sorted(home.iterdir()):
            try:
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
                removed += 1
            except OSError:
                pass
    else:
        for entry in sorted(data.iterdir()):
            try:
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
                removed += 1
            except OSError:
                pass

    print(f"  Done — removed {removed} item{'s' if removed != 1 else ''}.")
    print(f"  Start fresh with: {cli_invocation()} start")
    print()


def cmd_unpublish(args) -> None:
    """Revoke a network publish — removes the record from the registry."""
    from cruise_ai.network import unpublish

    print()
    try:
        print(f"  {unpublish()}")
    except RuntimeError as e:
        print(f"  {e}")
    print()


def cmd_network(args) -> None:
    """Network subcommands: serve (reference registry) / status."""
    action = getattr(args, "action", None)

    if action == "serve":
        from pathlib import Path as _Path

        from cruise_ai.network_server import run_registry

        store = getattr(args, "store", None)
        run_registry(
            port=getattr(args, "port", 7750) or 7750,
            host=getattr(args, "host", "127.0.0.1") or "127.0.0.1",
            store_dir=_Path(store) if store else None,
        )
        return

    # status (default)
    from cruise_ai.network import load_publish_state

    state = load_publish_state()
    print()
    if not state:
        print("  Not published. Your profile is local-only.")
        print(f"  To opt in: {cli_invocation()} publish")
    else:
        print("  Published (opt-in).")
        print(f"    Registry:   {state['registry']}")
        print(f"    Builder ID: {state['builderId']}")
        print(f"    Published:  {state.get('publishedAt', 'unknown')}")
        print(f"    Sections:   {', '.join(state.get('sections', []))}")
        print(f"  Revoke anytime: {cli_invocation()} unpublish")
    print()


def cmd_sources(args) -> None:
    """Show discovered data sources and collection summary."""
    from cruise_ai.adapters._registry import (
        get_git_adapter,
        get_session_adapters,
    )
    from cruise_ai.consent import load_collection_config

    non_interactive = getattr(args, "yes", False)
    enabled = _ensure_calibrated(non_interactive=non_interactive)
    collection_config = load_collection_config() or {}

    print()
    print("  cruise_ai — Discovered Sources")
    print("  " + "=" * 42)
    print()

    # Adapter name → consent group, shared with the scan path so this
    # display can never drift from what run_adapters actually gates on.
    from cruise_ai.adapters._registry import _CONSENT_KEYS as _consent_keys

    # Session adapters
    for adapter in get_session_adapters():
        consent_key = _consent_keys.get(adapter.name, "other_tools")
        if not enabled.get(consent_key, False):
            print(f"  {adapter.name.replace('_', ' ').title()}")
            print("    Status:     DISABLED (consent)")
            print()
            continue

        if not adapter.detect():
            print(f"  {adapter.name.replace('_', ' ').title()}")
            print("    Status:     NOT FOUND")
            print()
            continue

        adapter.scan()
        raw = adapter.raw_data()

        label = adapter.name.replace("_", " ").title()
        print(f"  {label}")

        if raw:
            path = raw.get("path", "")
            if path:
                print(f"    Path:       {path}")

            if adapter.name == "claude_code":
                print(f"    Sessions:   {raw.get('total_sessions', 0)}")
                earliest = raw.get("earliest", "")
                latest = raw.get("latest", "")
                if earliest and latest:
                    print(f"    Date range: {earliest[:10]} to {latest[:10]}")
            elif adapter.name == "cursor":
                ai_code = raw.get("ai_code") or {}
                scored = raw.get("scored_commits") or {}
                plans = raw.get("plans") or {}
                convos = raw.get("transcripts") or {}
                print(f"    AI blocks:  {ai_code.get('totalHashes', 0):,}")
                print(f"    Commits:    {scored.get('totalCommits', 0):,}")
                print(f"    Plans:      {plans.get('totalPlans', 0)}")
                print(f"    Transcripts: {convos.get('totalSessions', 0)}")
            elif adapter.name == "codex":
                print(f"    Sessions:   {raw.get('total_sessions', 0)}")
                earliest = raw.get("earliest", "")
                latest = raw.get("latest", "")
                if earliest and latest:
                    print(f"    Date range: {earliest[:10]} to {latest[:10]}")
            elif adapter.name == "kiro":
                print(f"    Sessions:   {raw.get('total_sessions', 0)}")
                cli_n = raw.get("cli_sessions", 0)
                ide_n = raw.get("ide_sessions", 0)
                if cli_n or ide_n:
                    print(f"    CLI / IDE:  {cli_n} / {ide_n}")
                if raw.get("subagent_sessions"):
                    print(f"    Subagents:  {raw.get('subagent_sessions', 0)}")
                earliest = raw.get("earliest", "")
                latest = raw.get("latest", "")
                if earliest and latest:
                    print(f"    Date range: {earliest[:10]} to {latest[:10]}")

        print("    Status:     COLLECTED")
        print()

    # Git adapter
    if not enabled.get("git", False):
        print("  Git")
        print("    Status:     DISABLED (consent)")
        print()
    else:
        git_adapter = get_git_adapter()
        # Collect session paths (quick re-scan of session adapters for paths)
        project_paths: list[str] = []
        for adapter in get_session_adapters():
            consent_key = _consent_keys.get(adapter.name, "other_tools")
            if not enabled.get(consent_key, False) or not adapter.detect():
                continue
            for s in adapter.scan():
                if s.project_path and s.project_path not in project_paths:
                    project_paths.append(s.project_path)

        window = collection_config.get("window")
        repos_cfg = collection_config.get("repos", "all")
        repo_filter = repos_cfg if isinstance(repos_cfg, list) else None

        git_data = git_adapter.scan_projects(
            project_paths,
            window=window,
            repo_filter=repo_filter,
        )

        print("  Git")
        if git_data:
            print(f"    Auto-discovered repos: {git_data.get('auto_discovered_repos', 0)}")
            print(f"    Repos from sessions:   {git_data.get('session_derived_repos', 0)}")
            print(f"    Total unique repos:    {git_data.get('total_repos', 0)}")
            w = collection_config.get("window", "6m_default")
            if w == "all":
                window_label = "all (full history)"
            elif isinstance(w, int):
                window_label = f"{w} days"
            else:
                window_label = "6 months (default)"
            print(f"    Window:                {window_label}")
            print("    Status:                COLLECTED")
        else:
            print("    Status:                NO REPOS FOUND")
        print()

    # Collection config summary
    print("  Collection Config")
    w = collection_config.get("window", "not set")
    r = collection_config.get("repos", "not set")
    print(f"    Window:  {w}")
    print(f"    Repos:   {r}")
    print()


# ── CLI entry point ──────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="cruise_ai",
        description="cruise_ai — Build your AI coding profile",
        epilog=(
            "the pipeline:  calibrate -> assess -> report -> enrich -> sync/publish\n"
            "run `cruise_ai guide` for the visual map of every step\n"
            "all local — nothing leaves your machine without an explicit opt-in"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # ── Subcommands ──────────────────────────────────────────────────────
    subparsers = parser.add_subparsers(dest="command")

    # calibrate
    cal = subparsers.add_parser(
        "calibrate",
        help="Onboarding: privacy disclosure, consent, collection scope",
    )
    cal.add_argument(
        "--yes", "-y", action="store_true", help="Non-interactive: accept all defaults"
    )

    # start — the one-shot pipeline
    start = subparsers.add_parser(
        "start",
        help="Everything in one go: calibrate (first run) + assess + report",
    )
    start.add_argument("--rescan", action="store_true", help="Force rescan, ignore cache")
    start.add_argument("--project", type=str, help="Scan a single project directory")
    start.add_argument(
        "--code",
        action="store_true",
        help="Opt-in local code scan: repo files reduced to metrics "
        "only (never stored, never sent)",
    )
    start.add_argument("--port", type=int, default=7749, help="Server port (default: 7749)")
    start.add_argument(
        "--live",
        action="store_true",
        help="Watch local sources and update open views in place (localhost only)",
    )
    start.add_argument(
        "--no-open",
        action="store_true",
        help="Don't open the browser automatically",
    )
    start.add_argument(
        "--yes", "-y", action="store_true", help="Non-interactive: accept all defaults"
    )

    # assess
    assess = subparsers.add_parser(
        "assess",
        help="Scan + score + write assessment JSON",
    )
    assess.add_argument("--rescan", action="store_true", help="Force rescan, ignore cache")
    assess.add_argument("--project", type=str, help="Scan a single project directory")
    assess.add_argument(
        "--code",
        action="store_true",
        help="Opt-in local code scan: repo files reduced to metrics "
        "only (never stored, never sent)",
    )
    assess.add_argument(
        "--yes", "-y", action="store_true", help="Non-interactive: accept all defaults"
    )

    # report
    report = subparsers.add_parser(
        "report",
        help="Start local profile server",
    )
    report.add_argument("--port", type=int, default=7749, help="Server port (default: 7749)")
    report.add_argument(
        "--live",
        action="store_true",
        help="Watch local sources and update open views in place (localhost only)",
    )
    report.add_argument(
        "--demo",
        action="store_true",
        help="Serve the bundled example profile (never touches your data)",
    )
    report.add_argument(
        "--no-open",
        action="store_true",
        help="Don't open the browser automatically",
    )
    report.add_argument(
        "--yes", "-y", action="store_true", help="Non-interactive: accept all defaults"
    )

    # sources
    sources = subparsers.add_parser(
        "sources",
        help="Show discovered data sources and collection summary",
    )
    sources.add_argument(
        "--yes", "-y", action="store_true", help="Non-interactive: accept all defaults"
    )

    # enrich
    enrich = subparsers.add_parser(
        "enrich",
        help="AI narrative enrichment — opt-in, runs on your own agent",
    )
    enrich.add_argument("--submit", type=str, help="Submit enrichment result JSON file")
    enrich.add_argument(
        "--revoke", action="store_true", help="Remove ingested enrichment, restore heuristic text"
    )
    enrich.add_argument("--key", type=str, help="Your API key for direct enrichment")
    enrich.add_argument(
        "--yes", "-y", action="store_true", help="Non-interactive: accept all defaults"
    )

    export = subparsers.add_parser(
        "export",
        help="Static self-hostable artifact (redacted shareable JSON + both views)",
    )
    export.add_argument(
        "--out",
        type=str,
        default="./cruise_ai-export",
        help="Output directory (default: ./cruise_ai-export)",
    )

    pub = subparsers.add_parser(
        "publish",
        help="Opt-in: publish your curated profile to a registry (revocable)",
    )
    pub.add_argument(
        "--registry", type=str, help="Registry URL (default: http://localhost:7750, self-hosted)"
    )
    pub.add_argument(
        "--confirm", action="store_true", help="Skip the interactive confirmation prompt"
    )
    pub.add_argument(
        "--dry-run", action="store_true", help="Show exactly what would be sent, send nothing"
    )

    subparsers.add_parser(
        "guide",
        help="Visual map of the pipeline: what each command does, reads, produces",
    )

    subparsers.add_parser(
        "unpublish",
        help="Revoke a publish: remove your profile from the registry",
    )

    reset = subparsers.add_parser(
        "reset",
        help="Delete local data and start fresh (profile, cache, consent, history)",
    )
    reset.add_argument(
        "--all",
        action="store_true",
        help="Also remove the rest of ~/.cruise_ai/ (registry store, sync clone, config)",
    )
    reset.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt")

    sync = subparsers.add_parser(
        "sync",
        help="Multi-device sync via YOUR OWN private git repo (derived-only, revocable)",
    )
    sync.add_argument(
        "--repo",
        type=str,
        help="Your PRIVATE sync repo URL (stored after first use)",
    )
    sync.add_argument("--status", action="store_true", help="Show sync state (no network)")
    sync.add_argument(
        "--revoke", action="store_true", help="Remove this device from the sync store"
    )
    sync.add_argument(
        "--yes", "-y", action="store_true", help="Skip the first-time confirmation prompt"
    )

    # ── recommend ───────────────────────────────────────────────────────
    recommend_p = subparsers.add_parser(
        "recommend",
        help="Get personalized recommendations based on your AI usage patterns",
    )
    recommend_p.add_argument(
        "--category",
        type=str,
        default=None,
        choices=["analytics", "token_optimization", "skills", "project_memory", "learning"],
        help="Filter recommendations by category",
    )
    recommend_p.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    recommend_p.add_argument(
        "--min-confidence",
        type=int,
        default=60,
        help="Minimum confidence threshold (default: 60)",
    )

    # ── dashboard ───────────────────────────────────────────────────────
    dashboard_p = subparsers.add_parser(
        "dashboard",
        help="Show AI usage analytics dashboard",
    )
    dashboard_p.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    # ── teach ────────────────────────────────────────────────────────────
    teach_p = subparsers.add_parser(
        "teach",
        help="Get step-by-step tutorials for AI productivity patterns",
    )
    teach_p.add_argument(
        "topic",
        nargs="?",
        default=None,
        help="Topic to learn (e.g. plan_mode, subagents, context_engineering, skills)",
    )

    # ── feedback ─────────────────────────────────────────────────────────
    feedback_p = subparsers.add_parser(
        "feedback",
        help="Provide feedback on recommendations (helps improve accuracy)",
    )
    feedback_p.add_argument(
        "response",
        nargs="?",
        choices=["acted", "dismissed", "useful", "not_useful"],
        help="Feedback type",
    )
    feedback_p.add_argument(
        "--action-type",
        type=str,
        help="The action_type of the recommendation",
    )
    feedback_p.add_argument(
        "--summary",
        action="store_true",
        help="Show feedback summary",
    )

    network = subparsers.add_parser(
        "network",
        help="Network utilities: serve a self-hosted registry, check status",
    )
    network.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=["serve", "status"],
        help="serve: run the reference registry; status: show publish state",
    )
    network.add_argument("--port", type=int, default=7750, help="Registry port (default: 7750)")
    network.add_argument(
        "--host", type=str, default="127.0.0.1", help="Bind host (default: 127.0.0.1)"
    )
    network.add_argument(
        "--store", type=str, help="Registry store directory (default: ~/.cruise_ai/registry)"
    )

    # ── Legacy top-level flags (backward compat) ────────────────────────
    parser.add_argument("--serve", action="store_true", help="Start profile server after building")
    parser.add_argument(
        "--live",
        action="store_true",
        # Deferred post-launch: accepted but inert (see cmd_report / hub.run_server).
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--rescan", action="store_true", help="Force rescan, ignore cache")
    parser.add_argument("--project", type=str, help="Scan a single project directory")
    parser.add_argument("--tools", action="store_true", help="List detected AI tools and exit")
    parser.add_argument("--port", type=int, default=7749, help="Server port (default: 7749)")
    parser.add_argument(
        "--reset-consent", action="store_true", help="Clear consent and re-prompt on next run"
    )
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Non-interactive: accept all sources"
    )
    parser.add_argument("--preview", action="store_true", help="Show collected scan data and exit")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show per-repo scan detail (quiet summaries by default)",
    )
    parser.add_argument("--version", action="version", version=f"cruise_ai {__version__}")

    # Friendly typo handling: suggest the nearest subcommand instead of
    # dumping usage ("caliberate" -> "calibrate")
    import difflib

    _commands = [
        "guide",
        "calibrate",
        "assess",
        "report",
        "sources",
        "enrich",
        "export",
        "publish",
        "unpublish",
        "reset",
        "network",
        "sync",
        "recommend",
        "dashboard",
        "teach",
        "feedback",
    ]
    argv = sys.argv[1:]
    first = next((a for a in argv if not a.startswith("-")), None)
    if first and first not in _commands:
        close = difflib.get_close_matches(first, _commands, n=1, cutoff=0.6)
        if close:
            print(f"Unknown command '{first}'. Did you mean '{close[0]}'?")
            raise SystemExit(2)

    args = parser.parse_args()
    if getattr(args, "verbose", False):
        os.environ["CRUISE_AI_VERBOSE"] = "1"

    # ── Route to subcommand or legacy behavior ──────────────────────────
    if args.command == "calibrate":
        cmd_calibrate(args)
    elif args.command == "start":
        cmd_start(args)
    elif args.command == "assess":
        cmd_assess(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "sources":
        cmd_sources(args)
    elif args.command == "enrich":
        cmd_enrich(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "publish":
        cmd_publish(args)
    elif args.command == "unpublish":
        cmd_unpublish(args)
    elif args.command == "reset":
        cmd_reset(args)
    elif args.command == "network":
        cmd_network(args)
    elif args.command == "sync":
        cmd_sync(args)
    elif args.command == "recommend":
        cmd_recommend(args)
    elif args.command == "dashboard":
        cmd_dashboard(args)
    elif args.command == "teach":
        cmd_teach(args)
    elif args.command == "feedback":
        cmd_feedback(args)
    elif args.command == "guide":
        from cruise_ai import cliui

        print()
        print(cliui.guide())
        print()
    else:
        # Legacy flag routing (no subcommand given)
        _handle_legacy(args)


def _handle_legacy(args) -> None:
    """Handle legacy top-level flags for backward compat."""
    from cruise_ai.paths import data_dir as _data_dir

    _data_dir()  # ensure directory exists

    # --tools mode
    if getattr(args, "tools", False):
        from cruise_ai.scanner import list_tools

        list_tools()
        return

    # --reset-consent
    if getattr(args, "reset_consent", False):
        from cruise_ai.consent import reset_consent

        reset_consent()
        print("  Consent cleared. Re-run to re-consent.")
        return

    # --preview
    if getattr(args, "preview", False):
        show_preview()
        return

    # Default: run assess (and optionally report if --serve)
    cmd_assess(args)

    if getattr(args, "serve", False):
        cmd_report(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(
            "\n  Stopped. Nothing was sent anywhere — your data stayed local.",
            file=sys.stderr,
        )
        sys.exit(130)
