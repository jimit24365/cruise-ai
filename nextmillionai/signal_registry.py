"""
nextmillionai.signal_registry — every derived field declares its inputs.

THE CORE RULE this module enforces: a displayed number must say where it
comes from, in code, not in someone's memory. Every derived field
carries:

  inputs — the data sources that feed it (see SOURCES). When an adapter
           gains a new source/generation, grep these to find every field
           that must be re-checked against its new denominator.
  rule   — one line: how it recomputes (union/max/sum/ratio/estimate).
  basis  — the honest scope a reader sees (which tools, which caps).

Tests enforce registration: ``build_wrapped_stats`` keys, profile
``signals`` keys, and the ledger-superseded fields must all be present
here — adding a metric without declaring its dependencies fails CI.

Recompute model: every ``assess`` recomputes ALL derived fields from
scratch (no incremental caching of derivations) — the registry exists
because the 2026-06-12 audit found fields whose *inputs* silently
lagged new sources (streak read Claude-only dates while the union knew
better). The failure mode is stale inputs, not stale outputs.
"""

from __future__ import annotations

# ── Input sources (the vocabulary `inputs` may use) ──────────────────────────
SOURCES = frozenset(
    {
        "claude_code.sessions",  # ~/.claude/projects JSONL (flat + subagents layouts)
        "claude_code.subagent_transcripts",  # <session>/subagents/agent-*.jsonl
        "cursor.composer_history",  # state.vscdb composer sessions (3 generations)
        "cursor.ai_tracking",  # ~/.cursor ai-code-tracking.db (hashes, scored commits)
        "cursor.scored_commits",  # per-commit AI/human line attribution
        "cursor.plans",  # ~/.cursor/plans
        "codex.sessions",  # ~/.codex/sessions (flat + date-nested)
        "other_tools.sessions",  # wider-field deep adapters (Cline/Continue/...)
        "git.commits",  # git log + manifests
        "ledger",  # durable history (supersedes live via max)
        "activity_union",  # per-day union: sessions + commits, all tools
        "local_models",  # Ollama / LM Studio / GGUF caches
        "research_band",  # published-literature anchor (estimates ONLY)
    }
)

#: Fields where the durable ledger supersedes live-scan values via max()
#: — tools prune their stores; measured history never regresses.
LEDGER_SUPERSEDED = frozenset(
    {
        "totalSessions",
        "totalEstimatedHours",
        "aiUsageSpanDays",
        "longestSessionMinutes",
        "deepSessionCount",
        "subagentDispatches",
        "marathonSessionCount",
        "sessionsWithSubagents",
        "maxParallelAgents",
        "agentRuntimeHours",
        "subagentRunCount",
        "longestStreakDays",  # superseded by the activity union, not the ledger
    }
)


def _d(inputs: list, rule: str, basis: str) -> dict:
    unknown = set(inputs) - SOURCES
    if unknown:  # fail at import time — a typo here is a lie downstream
        raise ValueError(f"unknown signal inputs: {unknown}")
    return {"inputs": inputs, "rule": rule, "basis": basis}


# ── The registry ─────────────────────────────────────────────────────────────
DERIVED: dict = {
    # wrappedStats (cards on both views)
    "maxParallelAgents": _d(
        ["claude_code.subagent_transcripts", "ledger"],
        "max(subagent-run transcript overlap peak [hard evidence], within-tool "
        "session span overlap [soft floor]); cross-tool overlap never counts",
        "overlapping agent-run transcripts prove true parallel execution; "
        "session-span overlap is the weaker fallback",
    ),
    "subagentDispatches": _d(
        ["claude_code.sessions", "claude_code.subagent_transcripts", "ledger"],
        "max(Task tool_use count, subagent run files) per session; ledger-accumulated",
        "Claude Code (only tool exposing dispatches)",
    ),
    "longestSessionMinutes": _d(
        ["claude_code.sessions", "cursor.composer_history", "codex.sessions", "ledger"],
        "max effective duration: gap-based active time (UNCAPPED — idle is "
        "already excluded, so it's real) where per-event timestamps exist, "
        "else span capped 480 min; ledger max-supersede",
        "active time for claude_code/codex; open-session span (8h cap) for cursor",
    ),
    "planModePercent": _d(
        ["claude_code.sessions"],
        "plan-before-code sessions / Claude Code sessions",
        "Claude Code only — other tools don't expose plan mode (stated on card)",
    ),
    "avgPromptsPerSession": _d(
        ["claude_code.sessions", "codex.sessions"],
        "mean parsed user prompts per session",
        "parsed-transcript tools only; Cursor bodies never read",
    ),
    "avgPromptWords": _d(
        ["claude_code.sessions", "codex.sessions"],
        "mean word count of parsed prompts",
        "parsed-transcript tools only (stated on card)",
    ),
    "longestStreakDays": _d(
        ["activity_union"],
        "max consecutive active days over the sessions+commits union",
        "all tools + git — never a single tool's calendar",
    ),
    "deepSessionCount": _d(
        ["claude_code.sessions", "cursor.composer_history", "codex.sessions", "ledger"],
        "sessions with effective duration > 30 min; ledger max-supersede",
        "active time where measured, span otherwise",
    ),
    "marathonSessionCount": _d(
        ["claude_code.sessions", "cursor.composer_history", "codex.sessions", "ledger"],
        "sessions with effective duration >= 2h (active time where measured, "
        "span-capped otherwise); recomputed from the ledger each assess",
        "the long-haul tier above deep (>30min); never a score input",
    ),
    "featureToFixRatio": _d(
        ["git.commits"],
        "conventional-commit prefix classification",
        "git history",
    ),
    "goToPrompt": _d(
        ["claude_code.sessions"],
        "requires enrichment (raw text not read by scoring)",
        "enrichment-gated; null otherwise",
    ),
    "tools": _d(["claude_code.sessions", "other_tools.sessions"], "detected CLI AI tools", "—"),
    "models": _d(
        ["claude_code.sessions", "cursor.ai_tracking", "codex.sessions", "local_models"],
        "most-frequent model from session metadata",
        "session metadata counts",
    ),
    "totalActiveHours": _d(
        ["claude_code.sessions", "cursor.composer_history", "codex.sessions", "ledger"],
        "sum of effective durations: gap-based active time (30min idle splits) "
        "where per-event timestamps exist, else span capped 8h; ledger-summed",
        "active time for claude_code/codex; open-session span for cursor — "
        "per-tool estimator stated on the card",
    ),
    "agentRuntimeHours": _d(
        ["claude_code.subagent_transcripts", "ledger"],
        "sum of run SPANS (8h cap) — agents execute continuously, so span is "
        "runtime; gap-splitting models human idling and would under-count; "
        "ledger max-supersede",
        "Claude Code subagent transcripts only — Cursor exposes no separate "
        "background-agent runtime (stated on card)",
    ),
    "subagentRunCount": _d(
        ["claude_code.subagent_transcripts", "ledger"],
        "count of agent-*.jsonl run files; ledger max-supersede",
        "Claude Code only",
    ),
    "peakProductivityHour": _d(
        ["claude_code.sessions"], "modal hour of session starts", "parsed-timestamp tools"
    ),
    "workMode": _d(
        ["claude_code.sessions", "cursor.ai_tracking", "git.commits"],
        "work-mode classifier over normalized metrics",
        "see SCORING-METHODOLOGY §3",
    ),
    "sessionsWithSubagents": _d(
        ["claude_code.sessions", "claude_code.subagent_transcripts", "ledger"],
        "count of sessions that dispatched ≥1 subagent; ledger-accumulated",
        "Claude Code only",
    ),
    "totalSessions": _d(
        ["claude_code.sessions", "cursor.composer_history", "codex.sessions", "ledger"],
        "live count, ledger max-supersede (deduped by tool:session_id)",
        "all dated tools + undated live extras",
    ),
    "totalEstimatedHours": _d(
        ["claude_code.sessions", "cursor.composer_history", "codex.sessions", "ledger"],
        "sum of effective durations (active time where measured, span-capped "
        "otherwise); ledger max-supersede",
        "two-tier estimator, stated as estimate; idle >30min never counts "
        "where transcripts allow measuring it",
    ),
    "aiUsageSpanDays": _d(
        ["ledger"],
        "days between earliest and latest dated session; ledger max-supersede",
        "session span — the wider git-backed evidence range is reported separately",
    ),
    # signals (hero numbers)
    "ai_code_blocks": _d(
        ["cursor.ai_tracking"],
        "count of tracked AI code-block hashes",
        "BLOCKS, not lines — fallback display when attribution absent",
    ),
    "ai_lines_survived": _d(
        ["cursor.scored_commits"],
        "sum of AI-attributed diff lines over tracked commits",
        "per-commit attribution; survival, not raw volume",
    ),
    "scored_commits": _d(["cursor.scored_commits"], "count of attribution-tracked commits", "—"),
    "architecture_plans": _d(["cursor.plans"], "plan file count", "file names only"),
    "models_used": _d(
        ["claude_code.sessions", "cursor.ai_tracking", "codex.sessions"],
        "distinct model ids",
        "session metadata",
    ),
    # activity block
    "streak": _d(["activity_union"], "same as longestStreakDays", "union"),
    "activeDays": _d(["activity_union"], "days with any session or commit", "union"),
    "avgSessionHours": _d(
        ["ledger"], "totalEstimatedHours / totalSessions", "ledger-backed totals"
    ),
    # leverage
    "aiShare": _d(
        ["cursor.scored_commits"],
        "aiLines / (aiLines + humanLines); insufficient < 10 commits or < 1000 lines",
        "tracked commits only",
    ),
    "outputMultiple": _d(
        ["cursor.scored_commits"],
        "(ai+human)/human, display-capped 50×; null when humanLines = 0",
        "counted, not estimated",
    ),
    "soloEquivalentHours": _d(
        ["cursor.scored_commits", "ledger", "research_band"],
        "hands-on hours × [1.33, 2.0] research band — ESTIMATE, Lab only",
        "labeled estimate; never a score input; never shareable",
    ),
}


def registered_fields() -> frozenset:
    return frozenset(DERIVED)
