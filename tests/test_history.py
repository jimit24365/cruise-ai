"""Tests for the durable local history ledger.

The promise under test: measured evidence survives its sources —
sessions pruned by Claude Code and deleted repos stay in the profile,
because they were real when measured. Local-only, never shared.
"""

from datetime import datetime, timedelta

import pytest

from cruise_ai.adapters._base import Session
from cruise_ai.history import (
    append_snapshot,
    ledger_orchestration,
    load_snapshots,
    update_activity_history,
    update_session_ledger,
)


@pytest.fixture(autouse=True)
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))


def make_session(sid, project="/p", task=0, start=None, hours=1):
    start = start or datetime(2026, 6, 1, 10, 0)
    return Session(
        tool="claude_code",
        session_id=sid,
        project_path=project,
        started_at=start,
        ended_at=start + timedelta(hours=hours),
        tool_calls_by_type={"task": task} if task else {},
        user_msgs=5,
    )


class TestSessionLedger:
    def test_evidence_survives_pruning(self):
        # First scan: two sessions with dispatches
        update_session_ledger([make_session("a", task=10), make_session("b", task=5)])
        # Claude prunes: second scan sees NOTHING — ledger keeps both
        ledger = update_session_ledger([])
        orch = ledger_orchestration(ledger)
        assert orch["subagentDispatches"] == 15
        assert orch["sessionsWithSubagents"] == 2
        assert orch["ledgerSessions"] == 2

    def test_resubmission_is_idempotent(self):
        s = make_session("a", task=10)
        update_session_ledger([s])
        ledger = update_session_ledger([s])  # rescan, same session
        assert ledger_orchestration(ledger)["subagentDispatches"] == 10

    def test_undated_sessions_not_recorded(self):
        s = Session(tool="cursor", session_id="x_tx_0", project_path=None)
        ledger = update_session_ledger([s])
        assert len(ledger) == 0

    def test_parallel_overlap_from_ledger(self):
        t0 = datetime(2026, 6, 1, 10, 0)
        update_session_ledger(
            [
                make_session("a", start=t0, hours=2),
                make_session("b", start=t0 + timedelta(minutes=30), hours=1),
            ]
        )
        orch = ledger_orchestration(update_session_ledger([]))
        assert orch["maxParallelAgents"] == 2
        assert orch["perProject"]["/p"]["maxParallel"] == 2


class TestActivityHistory:
    def test_days_survive_source_loss(self):
        update_activity_history(
            [{"date": "2026-01-05", "sessions": 4, "commits": 2, "tools": ["claude_code"]}]
        )
        # Later scan no longer sees January — union keeps it
        merged = update_activity_history(
            [{"date": "2026-06-01", "sessions": 1, "commits": 0, "tools": ["claude_code"]}]
        )
        dates = [d["date"] for d in merged]
        assert "2026-01-05" in dates and "2026-06-01" in dates

    def test_richer_record_wins(self):
        update_activity_history([{"date": "2026-06-01", "sessions": 1, "commits": 0}])
        merged = update_activity_history(
            [{"date": "2026-06-01", "sessions": 5, "commits": 2, "aiRatio": 80.0}]
        )
        day = next(d for d in merged if d["date"] == "2026-06-01")
        assert day["sessions"] == 5 and day["aiRatio"] == 80.0

    def test_weaker_rescan_does_not_erase(self):
        update_activity_history(
            [{"date": "2026-06-01", "sessions": 5, "commits": 2, "aiRatio": 80.0}]
        )
        merged = update_activity_history([{"date": "2026-06-01", "sessions": 0, "commits": 0}])
        day = next(d for d in merged if d["date"] == "2026-06-01")
        assert day["sessions"] == 5


class TestSnapshots:
    def test_one_per_day_last_wins(self):
        append_snapshot({"composite": 70})
        append_snapshot({"composite": 76})
        snaps = load_snapshots()
        assert len(snaps) == 1
        assert snaps[0]["composite"] == 76


# ── Durable totals (sessions / hours / span survive pruning) ────────────────


def test_ledger_totals_math():
    from cruise_ai.history import ledger_totals

    ledger = {
        "claude_code:a": {
            "start": "2026-04-01T10:00:00+00:00",
            "end": "2026-04-01T12:00:00+00:00",
            "agentRuns": 3,
            "agentMin": 90.0,
        },
        "claude_code:b": {
            "start": "2026-06-10T09:00:00+00:00",
            "end": "2026-06-10T10:30:00+00:00",
        },
    }
    t = ledger_totals(ledger)
    assert t["sessions"] == 2
    assert t["estimatedHours"] == 3.5
    assert t["agentRuns"] == 3
    assert t["agentHours"] == 1.5
    assert t["spanDays"] == 70
    assert t["earliest"] == "2026-04-01"
    assert t["latest"] == "2026-06-10"


def test_ledger_never_regresses_measured_work(tmp_path, monkeypatch):
    """Re-scanning after the tool pruned its store (or after a partial
    parse) must never lower task/agent counts already measured."""
    from datetime import datetime, timezone

    from cruise_ai.adapters._base import Session
    from cruise_ai.history import ledger_totals, update_session_ledger

    monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))
    rich = Session(
        tool="claude_code",
        session_id="s1",
        started_at=datetime(2026, 6, 1, 10, tzinfo=timezone.utc),
        ended_at=datetime(2026, 6, 1, 14, tzinfo=timezone.utc),
        tool_calls_by_type={"task": 7},
        extras={"subagentRuns": 7, "agentMinutes": 240.0},
    )
    update_session_ledger([rich])

    # Same session re-observed later with less detail (e.g. truncated file)
    poor = Session(
        tool="claude_code",
        session_id="s1",
        started_at=datetime(2026, 6, 1, 10, tzinfo=timezone.utc),
        ended_at=datetime(2026, 6, 1, 14, tzinfo=timezone.utc),
        tool_calls_by_type={},
        extras={},
    )
    ledger = update_session_ledger([poor])
    entry = ledger["claude_code:s1"]
    assert entry["task"] == 7
    assert entry["agentRuns"] == 7
    assert entry["agentMin"] == 240.0
    assert ledger_totals(ledger)["agentHours"] == 4.0


def test_ledger_totals_longest_and_deep():
    from cruise_ai.history import ledger_totals

    ledger = {
        "cursor:composer:x": {
            "start": "2026-06-01T10:00:00+00:00",
            "end": "2026-06-01T12:05:00+00:00",  # 125 min — deep + longest
        },
        "claude_code:y": {
            "start": "2026-06-02T10:00:00+00:00",
            "end": "2026-06-02T10:10:00+00:00",  # 10 min — not deep
        },
    }
    t = ledger_totals(ledger)
    assert t["longestSessionMinutes"] == 125
    assert t["deepSessionCount"] == 1


def test_parallel_is_per_tool_never_cross_tool():
    """A Cursor tab open beside a Claude session is multi-surface work,
    not 'two agents at once' — only within-tool overlap counts."""
    from cruise_ai.history import ledger_orchestration

    ledger = {
        "claude_code:a": {
            "tool": "claude_code",
            "project": "/p",
            "start": "2026-06-01T10:00:00",
            "end": "2026-06-01T12:00:00",
        },
        "cursor:b": {
            "tool": "cursor",
            "project": "/p",
            "start": "2026-06-01T10:30:00",
            "end": "2026-06-01T11:30:00",
        },
        # two genuinely-parallel cursor composers
        "cursor:c": {
            "tool": "cursor",
            "project": "/p",
            "start": "2026-06-01T10:40:00",
            "end": "2026-06-01T11:00:00",
        },
    }
    orch = ledger_orchestration(ledger)
    assert orch["maxParallelAgents"] == 2  # cursor b+c; never 3 cross-tool


def test_ledger_totals_prefer_active_minutes():
    """Effective duration: gap-based active time where measured; span
    (capped) only when a tool exposes nothing better."""
    from cruise_ai.history import ledger_totals

    ledger = {
        "claude_code:a": {  # measured active time wins over its 4h span
            "start": "2026-06-01T10:00:00+00:00",
            "end": "2026-06-01T14:00:00+00:00",
            "activeMin": 45.0,
        },
        "cursor:composer:b": {  # span-only tool falls back to capped span
            "start": "2026-06-02T10:00:00+00:00",
            "end": "2026-06-02T11:00:00+00:00",
        },
    }
    t = ledger_totals(ledger)
    assert t["estimatedHours"] == round((45 + 60) / 60, 1)  # 1.8, not 5.0
    assert t["longestSessionMinutes"] == 60
    assert t["deepSessionCount"] == 2


def test_ledger_totals_marathon_sessions():
    from cruise_ai.history import ledger_totals

    ledger = {
        "claude_code:a": {"start": "2026-06-01T10:00:00", "end": "2026-06-01T10:20:00"},  # 20m
        "claude_code:b": {"activeMin": 45.0, "start": "x", "end": "y"},  # deep, not marathon
        "claude_code:c": {"activeMin": 150.0, "start": "x", "end": "y"},  # marathon
        "cursor:d": {"start": "2026-06-02T08:00:00", "end": "2026-06-02T12:00:00"},  # 4h span
    }
    t = ledger_totals(ledger)
    assert t["marathonSessionCount"] == 2  # c (measured) + d (span)
    assert t["deepSessionCount"] == 3


def test_parallel_from_overlapping_subagent_runs():
    """Overlapping agent-run transcripts are the HARD parallelism
    evidence — they count even when no two sessions overlap."""
    from cruise_ai.history import ledger_orchestration

    ledger = {
        "claude_code:a": {
            "tool": "claude_code",
            "project": "/p",
            "start": "2026-06-01T10:00:00",
            "end": "2026-06-01T12:00:00",
            "runSpans": [
                ["2026-06-01T10:05:00", "2026-06-01T10:45:00"],
                ["2026-06-01T10:06:00", "2026-06-01T10:40:00"],
                ["2026-06-01T10:07:00", "2026-06-01T10:30:00"],
            ],
        },
    }
    orch = ledger_orchestration(ledger)
    assert orch["maxParallelAgents"] == 3
    assert orch["maxParallelMeasuredRuns"] == 3
    # Per-project footprint pools the parent session WITH its runs:
    # the orchestrating session + 3 subagents = 4 agents working there
    assert orch["perProject"]["/p"]["maxParallel"] == 4


class TestSubagentChildLedger:
    """Subagent CHILD sessions (kiro-style orchestration) are agent
    runtime in the ledger — never the user's own sessions or hours."""

    def _child(self, sid: str, minutes: int):
        from datetime import datetime, timedelta, timezone

        from cruise_ai.adapters._base import Session

        start = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        return Session(
            tool="kiro",
            session_id=sid,
            started_at=start,
            ended_at=start + timedelta(minutes=minutes),
            user_msgs=1,
            assistant_msgs=1,
            extras={"is_subagent": True, "parent_session_id": "parent-1"},
        )

    def _parent(self, minutes: int = 60):
        from datetime import datetime, timedelta, timezone

        from cruise_ai.adapters._base import Session

        start = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
        return Session(
            tool="kiro",
            session_id="parent-1",
            started_at=start,
            ended_at=start + timedelta(minutes=minutes),
            user_msgs=5,
            assistant_msgs=5,
        )

    def test_children_book_as_agent_runtime_not_sessions(self, tmp_path, monkeypatch):
        from cruise_ai.history import ledger_totals, update_session_ledger

        monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))
        ledger = update_session_ledger(
            [self._parent(60), self._child("c1", 30), self._child("c2", 45)]
        )
        totals = ledger_totals(ledger)

        assert totals["sessions"] == 1  # the parent only
        assert totals["estimatedHours"] == 1.0  # 60 min, children excluded
        assert totals["agentRuns"] == 2
        assert totals["agentHours"] == round(75 / 60.0, 1)

    def test_subagent_flag_survives_remerge(self, tmp_path, monkeypatch):
        """A later rescan must never demote a recorded child to a user
        session (the flag is one-way, like every ledger max-guard)."""
        from cruise_ai.history import ledger_totals, update_session_ledger

        monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))
        update_session_ledger([self._child("c1", 30)])
        # Re-merge the same session WITHOUT the extras (pruned metadata)
        from datetime import datetime, timedelta, timezone

        from cruise_ai.adapters._base import Session

        start = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        bare = Session(
            tool="kiro",
            session_id="c1",
            started_at=start,
            ended_at=start + timedelta(minutes=30),
            user_msgs=1,
        )
        ledger = update_session_ledger([bare])
        totals = ledger_totals(ledger)
        assert totals["sessions"] == 0
        assert totals["agentRuns"] == 1
