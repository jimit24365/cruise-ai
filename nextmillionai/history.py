"""
nextmillionai.history -- Durable local evidence ledger.

Claude Code prunes old session files and users delete repos — without a
ledger, real measured work silently vanishes from the profile. This
module keeps an append-only, LOCAL-ONLY record so evidence survives its
sources:

  history/sessions.json   — one entry per session ever observed
                            (id, tool, project, span, task dispatches)
  history/activity.json   — per-day activity union across all scans
  history/snapshots.jsonl — one compact metrics snapshot per assess-day
                            (powers honest you-vs-you trends over time)

Everything lives under ~/.nextmillionai/data/history/ — same privacy
class as scan_results.json: local files, never shared, never uploaded.
Entries record what WAS measured at the time; nothing is estimated.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from nextmillionai.adapters._base import Session
from nextmillionai.paths import data_dir


def history_dir() -> Path:
    d = data_dir() / "history"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, type(default)) else default
    except (json.JSONDecodeError, OSError):
        return default


def _dump_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=1, default=str))


# ── Session ledger ───────────────────────────────────────────────────────────


def update_session_ledger(sessions: list[Session]) -> dict:
    """Merge currently-visible sessions into the ledger; return the full
    ledger (old + new). Only sessions with real timestamps are recorded —
    a ledger of undated entries would be noise, not history."""
    path = history_dir() / "sessions.json"
    ledger: dict = _load_json(path, {})

    for s in sessions:
        if not s.session_id or not s.started_at:
            continue
        key = f"{s.tool}:{s.session_id}"
        extras = s.extras or {}
        entry = {
            "tool": s.tool,
            "project": s.project_path,
            "start": s.started_at.isoformat(),
            "end": s.ended_at.isoformat() if s.ended_at else None,
            "task": (s.tool_calls_by_type or {}).get("task", 0),
            "userMsgs": s.user_msgs,
            # Subagent CHILD session (kiro-style orchestration): agent
            # runtime, never the user's own session — ledger_totals books
            # it under agentRuns/agentHours, not sessions/hours.
            "subagent": bool(extras.get("is_subagent")),
            # Subagent runtime (measured from agent-*.jsonl transcripts)
            "agentRuns": extras.get("subagentRuns", 0) or 0,
            "agentMin": extras.get("agentMinutes", 0) or 0,
            "runSpans": extras.get("agentRunSpans") or [],
            # Gap-based active minutes (30min idle splits) where the
            # tool's transcript carries per-event timestamps; absent
            # for span-only tools (e.g. Cursor composer scalars)
            "activeMin": extras.get("activeMinutes") or 0,
            "firstSeen": ledger.get(key, {}).get(
                "firstSeen", datetime.now(timezone.utc).strftime("%Y-%m-%d")
            ),
        }
        # Never let a re-scan of a pruned/empty store erase measured work
        old = ledger.get(key, {})
        entry["subagent"] = entry["subagent"] or bool(old.get("subagent"))
        entry["task"] = max(entry["task"], old.get("task", 0) or 0)
        entry["agentRuns"] = max(entry["agentRuns"], old.get("agentRuns", 0) or 0)
        entry["agentMin"] = max(entry["agentMin"], old.get("agentMin", 0) or 0)
        entry["activeMin"] = max(entry["activeMin"], old.get("activeMin", 0) or 0)
        if not entry["runSpans"] and old.get("runSpans"):
            entry["runSpans"] = old["runSpans"]  # pruned runs stay measured
        ledger[key] = entry

    _dump_json(path, ledger)
    return ledger


def ledger_orchestration(ledger: dict) -> dict:
    """Durable orchestration evidence from the full ledger: per-project
    Task dispatches + same-project parallel overlap, plus global totals.
    Survives session pruning — these runs happened and were measured."""
    per_project: dict = {}
    spans_by_project: dict = {}
    spans_by_tool: dict = {}
    run_spans: list = []  # subagent runs: agents truly executing at once
    dispatches = 0
    dispatch_sessions = 0

    for entry in ledger.values():
        proj = entry.get("project")
        tool = entry.get("tool") or "unknown"
        task = entry.get("task", 0) or 0
        if task:
            dispatches += task
            dispatch_sessions += 1
        start, end = entry.get("start"), entry.get("end")
        if start and end:
            # Parallelism is measured WITHIN a tool: a Cursor tab open
            # beside a Claude session is multi-surface work, not "two
            # agents at once" — cross-tool overlap never counts.
            spans_by_tool.setdefault(tool, []).append((start, end))
        for span in entry.get("runSpans") or []:
            if isinstance(span, (list, tuple)) and len(span) == 2:
                run_spans.append((span[0], span[1]))
                if entry.get("project"):
                    spans_by_project.setdefault((entry["project"], tool), []).append(
                        (span[0], span[1])
                    )
        if not proj:
            continue
        p = per_project.setdefault(
            proj, {"dispatches": 0, "sessionsWithDispatch": 0, "maxParallel": 1}
        )
        if task:
            p["dispatches"] += task
            p["sessionsWithDispatch"] += 1
        if start and end:
            spans_by_project.setdefault((proj, tool), []).append((start, end))

    def _peak(spans):
        events = []
        for a, b in spans:
            events.append((a, 1))
            events.append((b, -1))
        events.sort(key=lambda e: (e[0], e[1]))
        cur = peak = 0
        for _, delta in events:
            cur += delta
            peak = max(peak, cur)
        return peak

    for (proj, _tool), spans in spans_by_project.items():
        per_project[proj]["maxParallel"] = max(per_project[proj]["maxParallel"], _peak(spans))

    # Subagent-run overlap is the HARD evidence (transcript-timestamped
    # parallel execution); within-tool session overlap is the softer
    # floor. Take the max of both.
    session_peak = max((_peak(s) for s in spans_by_tool.values()), default=1)
    run_peak = _peak(run_spans) if run_spans else 0
    max_parallel = max(session_peak, run_peak, 1)

    return {
        "perProject": {
            k: v for k, v in per_project.items() if v["dispatches"] or v["maxParallel"] > 1
        },
        "subagentDispatches": dispatches,
        "sessionsWithSubagents": dispatch_sessions,
        "maxParallelAgents": max_parallel,
        "maxParallelMeasuredRuns": run_peak,
        "ledgerSessions": len(ledger),
    }


def ledger_totals(ledger: dict) -> dict:
    """Durable totals from every session ever observed.

    Claude Code prunes old transcripts — live-scan totals shrink as the
    store ages out, but the ledger remembers what WAS measured. These
    totals supersede live values via max() in the pipeline so hours,
    session counts and the usage span never silently regress. Durations
    are capped at 8h per session, same as everywhere else; agent runtime
    (subagent runs) is kept separate from the user's own session hours.
    """
    sessions = 0
    minutes = 0.0
    longest_min = 0.0
    deep_sessions = 0
    marathon_sessions = 0
    agent_runs = 0
    agent_minutes = 0.0
    earliest: str | None = None
    latest: str | None = None

    for entry in ledger.values():
        start, end = entry.get("start"), entry.get("end")
        if start:
            if earliest is None or start < earliest:
                earliest = start
            if latest is None or start > latest:
                latest = start
        if end and (latest is None or end > latest):
            latest = end
        # Effective duration: gap-based ACTIVE minutes where the tool's
        # transcript carried per-event timestamps (real data, idle never
        # counts); first-to-last span capped 8h where only two
        # timestamps exist. Better measurement legitimately LOWERS a
        # number — never-regress applies to evidence, not to estimator
        # inflation.
        dur = entry.get("activeMin") or 0
        if not dur and start and end:
            try:
                a = datetime.fromisoformat(start)
                b = datetime.fromisoformat(end)
                dur = min(max((b - a).total_seconds() / 60.0, 0), 480)
            except (ValueError, TypeError):
                dur = 0
        if entry.get("subagent"):
            # A subagent CHILD session is agent runtime the parent
            # dispatched — never the user's own session or hours (same
            # separation as Claude Code's agentRuns/agentMin).
            agent_runs += 1
            agent_minutes += dur
            continue
        sessions += 1
        if dur:
            minutes += dur
            longest_min = max(longest_min, dur)
            if dur > 30:
                deep_sessions += 1
            if dur >= 120:
                marathon_sessions += 1
        agent_runs += entry.get("agentRuns", 0) or 0
        agent_minutes += entry.get("agentMin", 0) or 0

    span_days = 0
    if earliest and latest:
        try:
            span_days = (
                datetime.fromisoformat(latest[:10]) - datetime.fromisoformat(earliest[:10])
            ).days
        except (ValueError, TypeError):
            span_days = 0

    return {
        "sessions": sessions,
        "estimatedHours": round(minutes / 60.0, 1),
        "longestSessionMinutes": round(longest_min),
        "deepSessionCount": deep_sessions,
        "marathonSessionCount": marathon_sessions,
        "agentRuns": agent_runs,
        "agentHours": round(agent_minutes / 60.0, 1),
        "spanDays": span_days,
        "earliest": earliest[:10] if earliest else None,
        "latest": latest[:10] if latest else None,
    }


# ── Activity history (per-day union) ─────────────────────────────────────────


def update_activity_history(activity_by_day: list[dict]) -> list[dict]:
    """Union today's scan with every prior scan, per day. For each day we
    keep the RICHER record (max sessions/commits, known aiRatio over
    unknown) — pruned sources stop contributing, history does not."""
    path = history_dir() / "activity.json"
    store: dict = _load_json(path, {})

    def _units(d):
        return (d.get("sessions") or 0) + (d.get("commits") or 0)

    for day in activity_by_day:
        date = day.get("date")
        if not date:
            continue
        old = store.get(date)
        if old is None:
            store[date] = day
            continue
        merged = dict(old)
        if _units(day) > _units(old):
            merged.update({k: day.get(k) for k in ("sessions", "commits", "activeMinutes")})
        if day.get("topProject") and not old.get("topProject"):
            merged["topProject"] = day["topProject"]
        merged["tools"] = sorted(set(old.get("tools") or []) | set(day.get("tools") or []))
        if day.get("aiRatio") is not None:
            merged["aiRatio"] = day["aiRatio"]
        store[date] = merged

    _dump_json(path, store)
    return [store[k] for k in sorted(store.keys())]


# ── Metric snapshots (you-vs-you over real time) ─────────────────────────────


def append_snapshot(snapshot: dict) -> None:
    """One compact snapshot per assess-day (last write of the day wins).
    These power honest longitudinal trends that need no cohort."""
    path = history_dir() / "snapshots.jsonl"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snapshot = {"date": today, **snapshot}

    lines = []
    if path.is_file():
        try:
            lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        except (json.JSONDecodeError, OSError):
            lines = []
    lines = [s for s in lines if s.get("date") != today]
    lines.append(snapshot)
    path.write_text("\n".join(json.dumps(s) for s in lines) + "\n")


def load_snapshots() -> list[dict]:
    path = history_dir() / "snapshots.jsonl"
    if not path.is_file():
        return []
    try:
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except (json.JSONDecodeError, OSError):
        return []
