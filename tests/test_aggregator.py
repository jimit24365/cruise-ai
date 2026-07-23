"""Tests for the aggregator module.

Tests compute_normalized_from_sessions() and build_signal_matrix()
using Session objects built from fixtures.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nextmillionai.adapters._base import Session
from nextmillionai.adapters.claude_code import ClaudeCodeAdapter
from nextmillionai.aggregator import (
    build_activity_by_day,
    build_models_summary,
    build_scanned_projects,
    build_signal_matrix,
    build_stack_summary,
    build_summary_line,
    compute_normalized_from_sessions,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def claude_sessions(tmp_path):
    """Build Session objects from fixture JSONL files."""
    projects_dir = tmp_path / ".claude" / "projects"
    proj_dir = projects_dir / "-Users-dev-my-project"
    proj_dir.mkdir(parents=True)
    shutil.copy(FIXTURES / "sample_session.jsonl", proj_dir / "session_abc.jsonl")
    shutil.copy(FIXTURES / "second_session.jsonl", proj_dir / "session_def.jsonl")

    adapter = ClaudeCodeAdapter(projects_dir=projects_dir)
    sessions = adapter.scan()
    raw = adapter.raw_data()
    return sessions, {"claude_code": raw, "cursor": None, "codex": None}


class TestComputeNormalizedFromSessions:
    def test_total_sessions(self, claude_sessions):
        sessions, raw_data = claude_sessions
        n = compute_normalized_from_sessions(sessions, raw_data, None)
        assert n["totalSessions"] == 2

    def test_avg_turns_per_task(self, claude_sessions):
        """session_abc: 3 user msgs, session_def: 2 user msgs.
        avgTurnsPerTask = 5 / 2 = 2.5"""
        sessions, raw_data = claude_sessions
        n = compute_normalized_from_sessions(sessions, raw_data, None)
        assert n["avgTurnsPerTask"] == 2.5

    def test_avg_prompt_words(self, claude_sessions):
        """28 total words / 5 user msgs = 5.6 -> rounds to 6."""
        sessions, raw_data = claude_sessions
        n = compute_normalized_from_sessions(sessions, raw_data, None)
        assert n["avgPromptWords"] == 6

    def test_terminal_command_count(self, claude_sessions):
        """session_abc: 2 Bash, session_def: 0 -> 2 total."""
        sessions, raw_data = claude_sessions
        n = compute_normalized_from_sessions(sessions, raw_data, None)
        assert n["terminalCommandCount"] == 2

    def test_files_per_session(self, claude_sessions):
        """session_abc: 3 file tools, session_def: 4 file tools.
        Total: 7 / 2 sessions = 3.5"""
        sessions, raw_data = claude_sessions
        n = compute_normalized_from_sessions(sessions, raw_data, None)
        assert n["filesPerSession"] == 3.5

    def test_max_parallel_agents(self, claude_sessions):
        sessions, raw_data = claude_sessions
        n = compute_normalized_from_sessions(sessions, raw_data, None)
        assert "maxParallelAgents" in n
        assert n["maxParallelAgents"] >= 1

    def test_deep_session_count(self, claude_sessions):
        sessions, raw_data = claude_sessions
        n = compute_normalized_from_sessions(sessions, raw_data, None)
        assert "deepSessionCount" in n
        assert isinstance(n["deepSessionCount"], int)

    def test_plan_mode_percent(self, claude_sessions):
        sessions, raw_data = claude_sessions
        n = compute_normalized_from_sessions(sessions, raw_data, None)
        assert "planModePercent" in n

    def test_empty_sessions(self):
        n = compute_normalized_from_sessions(
            [], {"claude_code": None, "cursor": None, "codex": None}, None
        )
        assert n["totalSessions"] == 0
        assert n["planModePercent"] == 0.0

    def test_peak_productivity_hour_default(self):
        n = compute_normalized_from_sessions(
            [], {"claude_code": None, "cursor": None, "codex": None}, None
        )
        assert n["peakProductivityHour"] == 14

    def test_longest_streak_zero(self):
        n = compute_normalized_from_sessions(
            [], {"claude_code": None, "cursor": None, "codex": None}, None
        )
        assert n["longestStreakDays"] == 0


class TestBuildSignalMatrix:
    def test_basic_structure(self, claude_sessions):
        sessions, _ = claude_sessions
        matrix = build_signal_matrix(sessions)
        assert "projects" in matrix
        assert len(matrix["projects"]) > 0

    def test_project_fields(self, claude_sessions):
        sessions, _ = claude_sessions
        matrix = build_signal_matrix(sessions)
        proj = matrix["projects"][0]
        assert "project_path" in proj
        assert "project_name" in proj
        assert "agents" in proj

    def test_agent_fields(self, claude_sessions):
        sessions, _ = claude_sessions
        matrix = build_signal_matrix(sessions)
        proj = matrix["projects"][0]
        agent = proj["agents"]["claude_code"]
        assert "session_count" in agent
        assert "total_user_msgs" in agent
        assert "total_tool_calls" in agent
        assert "models" in agent
        assert "earliest" in agent
        assert "latest" in agent

    def test_session_count_matches(self, claude_sessions):
        sessions, _ = claude_sessions
        matrix = build_signal_matrix(sessions)
        proj = matrix["projects"][0]
        assert proj["agents"]["claude_code"]["session_count"] == 2

    def test_multi_tool_grouping(self):
        """Sessions from different tools should be grouped separately."""
        sessions = [
            Session(
                tool="claude_code",
                session_id="c1",
                project_path="/app",
                user_msgs=5,
                started_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
                ended_at=datetime(2024, 6, 1, 1, tzinfo=timezone.utc),
            ),
            Session(
                tool="codex",
                session_id="x1",
                project_path="/app",
                user_msgs=3,
                started_at=datetime(2024, 6, 2, tzinfo=timezone.utc),
                ended_at=datetime(2024, 6, 2, 1, tzinfo=timezone.utc),
            ),
        ]
        matrix = build_signal_matrix(sessions)
        assert len(matrix["projects"]) == 1
        agents = matrix["projects"][0]["agents"]
        assert "claude_code" in agents
        assert "codex" in agents
        assert agents["claude_code"]["session_count"] == 1
        assert agents["codex"]["session_count"] == 1

    def test_empty_sessions(self):
        matrix = build_signal_matrix([])
        assert matrix == {"projects": []}


# ── Front-end view builders ──────────────────────────────────────────────────


def _make_sessions():
    """Two sessions on different days for testing."""
    return [
        Session(
            tool="claude_code",
            session_id="s1",
            project_path="/Users/dev/app-one",
            user_msgs=5,
            assistant_msgs=3,
            models=["claude-opus-4-6"],
            started_at=datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc),
            ended_at=datetime(2024, 6, 1, 11, 30, tzinfo=timezone.utc),
            tool_calls_by_type={"file": 3, "terminal": 1},
            prompt_word_counts=[10, 5, 8, 4, 3],
        ),
        Session(
            tool="codex",
            session_id="s2",
            project_path="/Users/dev/app-one",
            user_msgs=2,
            assistant_msgs=2,
            models=["o3"],
            started_at=datetime(2024, 6, 3, 14, 0, tzinfo=timezone.utc),
            ended_at=datetime(2024, 6, 3, 14, 45, tzinfo=timezone.utc),
            tool_calls_by_type={"file": 1},
            prompt_word_counts=[20, 15],
        ),
    ]


class TestActivityByDay:
    def test_empty_sessions(self):
        assert build_activity_by_day([]) == []

    def test_day_count(self):
        """Two sessions on June 1 and June 3 -> 3 days (1, 2, 3)."""
        result = build_activity_by_day(_make_sessions())
        assert len(result) == 3
        dates = [r["date"] for r in result]
        assert dates == ["2024-06-01", "2024-06-02", "2024-06-03"]

    def test_active_day(self):
        result = build_activity_by_day(_make_sessions())
        day1 = result[0]
        assert day1["sessions"] == 1
        assert day1["activeMinutes"] == 90.0  # 1.5h
        assert day1["tools"] == ["claude_code"]
        assert day1["topProject"] == "app-one"

    def test_inactive_day(self):
        result = build_activity_by_day(_make_sessions())
        day2 = result[1]  # June 2 - no sessions
        assert day2["sessions"] == 0
        assert day2["activeMinutes"] is None
        assert day2["tools"] == []
        assert day2["topProject"] is None

    def test_ai_ratio_none_without_cursor(self):
        result = build_activity_by_day(_make_sessions())
        for day in result:
            assert day["aiRatio"] is None

    def test_ai_ratio_from_cursor_commits(self):
        cursor_data = {
            "scored_commits": {
                "recentCommits": [
                    {
                        "hash": "abc",
                        "message": "fix",
                        "date": "2024-06-01T12:00:00Z",
                        "aiPct": 0.75,
                    },
                ],
            },
        }
        result = build_activity_by_day(_make_sessions(), cursor_data)
        assert result[0]["aiRatio"] == 0.75
        assert result[1]["aiRatio"] is None  # June 2 — no commit

    def test_cursor_only_day_outside_session_range(self):
        """A Cursor commit on a day with NO session must still appear with non-null aiRatio."""
        # Sessions span June 1–3; Cursor commit is on June 5 (outside range)
        cursor_data = {
            "scored_commits": {
                "recentCommits": [
                    {
                        "hash": "abc",
                        "message": "fix",
                        "date": "2024-06-05T10:00:00Z",
                        "aiPct": 0.60,
                    },
                ],
            },
        }
        result = build_activity_by_day(_make_sessions(), cursor_data)
        dates = [r["date"] for r in result]
        # Range should now extend to June 5
        assert "2024-06-05" in dates
        day5 = next(r for r in result if r["date"] == "2024-06-05")
        assert day5["aiRatio"] == 0.60
        assert day5["sessions"] == 0  # no session on that day
        assert day5["activeMinutes"] is None

    def test_git_only_day_extends_range(self):
        """A git commit date outside the session range extends the output range."""
        git_data = {
            "projects": [
                {
                    "path": "/Users/dev/app-one",
                    "name": "app-one",
                    "commit_dates": ["2024-05-30T08:00:00Z"],
                },
            ],
        }
        result = build_activity_by_day(_make_sessions(), git_data=git_data)
        dates = [r["date"] for r in result]
        # Range should start at May 30 (git) through June 3 (session)
        assert dates[0] == "2024-05-30"
        assert dates[-1] == "2024-06-03"
        # May 30 has no session and no cursor data
        day_may30 = result[0]
        assert day_may30["sessions"] == 0
        assert day_may30["aiRatio"] is None

    def test_cursor_only_no_sessions(self):
        """With zero sessions, Cursor data alone should produce output."""
        cursor_data = {
            "scored_commits": {
                "recentCommits": [
                    {
                        "hash": "a1",
                        "message": "thing",
                        "date": "2024-07-10T12:00:00Z",
                        "aiPct": 0.80,
                    },
                    {
                        "hash": "a2",
                        "message": "stuff",
                        "date": "2024-07-12T14:00:00Z",
                        "aiPct": 0.50,
                    },
                ],
            },
        }
        result = build_activity_by_day([], cursor_data)
        assert len(result) == 3  # July 10, 11, 12
        dates = [r["date"] for r in result]
        assert dates == ["2024-07-10", "2024-07-11", "2024-07-12"]
        assert result[0]["aiRatio"] == 0.80
        assert result[1]["aiRatio"] is None  # gap day
        assert result[2]["aiRatio"] == 0.50

    def test_no_synthetic_values(self):
        result = build_activity_by_day(_make_sessions())
        for day in result:
            for _key, val in day.items():
                if isinstance(val, str):
                    assert "<synthetic>" not in val


class TestScannedProjects:
    def test_empty(self):
        assert build_scanned_projects([], None) == []

    def test_from_sessions(self):
        result = build_scanned_projects(_make_sessions())
        assert len(result) == 1
        assert result[0]["name"] == "app-one"
        assert result[0]["sessionCount"] == 2
        assert result[0]["lastActive"] == "2024-06-03"

    def test_enriched_with_git(self):
        git_data = {
            "projects": [
                {
                    "path": "/Users/dev/app-one",
                    "name": "app-one",
                    "languages": ["Python", "TypeScript"],
                    "frameworks": ["FastAPI"],
                },
            ],
        }
        result = build_scanned_projects(_make_sessions(), git_data)
        assert result[0]["languages"] == ["Python", "TypeScript"]

    def test_git_only_project(self):
        """A git project with no sessions still appears."""
        git_data = {
            "projects": [
                {
                    "path": "/Users/dev/other",
                    "name": "other",
                    "languages": ["Go"],
                    "frameworks": [],
                },
            ],
        }
        result = build_scanned_projects([], git_data)
        assert len(result) == 1
        assert result[0]["name"] == "other"
        assert result[0]["sessionCount"] == 0

    def test_no_synthetic_names(self):
        result = build_scanned_projects(_make_sessions())
        for p in result:
            assert "<synthetic>" not in p["name"]


class TestStackSummary:
    def test_empty(self):
        result = build_stack_summary(None)
        assert result == {
            "languages": {},
            "frameworks": [],
            "aiFrameworks": [],
            "databases": [],
            "cloud": [],
        }

    def test_languages_weighted(self):
        git_data = {
            "projects": [
                {"path": "/a", "languages": ["Python", "JS"], "frameworks": ["FastAPI"]},
                {"path": "/b", "languages": ["Python"], "frameworks": ["Django"]},
            ],
        }
        result = build_stack_summary(git_data)
        assert "Python" in result["languages"]
        # Python appears in 2/3 lang mentions
        assert result["languages"]["Python"] > result["languages"]["JS"]
        assert sorted(result["frameworks"]) == ["Django", "FastAPI"]

    def test_weights_sum_to_one(self):
        git_data = {
            "projects": [
                {"path": "/a", "languages": ["Python", "JS"], "frameworks": []},
                {"path": "/b", "languages": ["Go"], "frameworks": []},
            ],
        }
        result = build_stack_summary(git_data)
        total = sum(result["languages"].values())
        assert abs(total - 1.0) < 0.01


class TestModelsSummary:
    def test_empty(self):
        result = build_models_summary([], {"cursor": None})
        assert result == {"byModel": {}, "primaryModel": None}

    def test_from_sessions(self):
        result = build_models_summary(_make_sessions(), {"cursor": None})
        assert "claude-opus-4-6" in result["byModel"]
        assert "o3" in result["byModel"]
        assert result["primaryModel"] in ("claude-opus-4-6", "o3")

    def test_empty_model_excluded_from_output(self):
        sessions = [
            Session(
                tool="test",
                session_id="x",
                models=["", "  "],
                started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                ended_at=datetime(2024, 1, 1, 1, tzinfo=timezone.utc),
            ),
        ]
        result = build_models_summary(sessions, {"cursor": None})
        assert "unknown" not in result["byModel"]
        assert "<synthetic>" not in str(result)

    def test_no_synthetic_models(self):
        result = build_models_summary(_make_sessions(), {"cursor": None})
        for model in result["byModel"]:
            assert "<synthetic>" not in model

    def test_cursor_default_placeholder_never_wins_go_to_model(self):
        # Cursor records "default"/"auto" when no model is pinned; it must not
        # masquerade as the go-to model when a real model exists (Builder Profile bug).
        cursor = {"cursor": {"ai_code": {"byModel": {"default": 40, "claude-opus-4-7": 1}}}}
        result = build_models_summary([], cursor)
        assert result["primaryModel"] == "claude-opus-4-7"
        assert "default" not in result["byModel"]
        assert "unknown" not in result["byModel"]
        # Cursor placeholders are labeled honestly — tool usage is visible
        assert result["byModel"].get("cursor (auto-select)") == 40


class TestSummaryLine:
    def test_none_without_data(self):
        assert build_summary_line(None, None, None) is None

    def test_basic_format(self):
        work_mode = {"dominant": {"id": "One-Shot-Verify", "line": "..."}}
        dims = {
            "signal_clarity": {"score": 85, "weight": 0.18},
            "orchestration_range": {"score": 78, "weight": 0.15},
            "build_stability": {"score": 60, "weight": 0.22},
            "decision_weight": {"score": 55, "weight": 0.18},
            "recovery_velocity": {"score": 70, "weight": 0.15},
            "context_command": {"score": 65, "weight": 0.12},
        }
        normalized = {"maxParallelAgents": 3, "totalSessions": 50}
        line = build_summary_line(work_mode, dims, normalized)
        assert line is not None
        assert "Ships" in line
        assert "One Shot Verify" in line
        assert "Signal Clarity" in line
        assert "3 parallel agents" in line

    def test_architect_verb(self):
        work_mode = {"dominant": {"id": "Architect-First", "line": "..."}}
        dims = {
            "decision_weight": {"score": 90, "weight": 0.18},
            "context_command": {"score": 80, "weight": 0.12},
            "signal_clarity": {"score": 60, "weight": 0.18},
            "build_stability": {"score": 50, "weight": 0.22},
            "recovery_velocity": {"score": 50, "weight": 0.15},
            "orchestration_range": {"score": 40, "weight": 0.15},
        }
        line = build_summary_line(work_mode, dims, {})
        assert "Architects" in line
        assert "Decision Weight" in line

    def test_no_synthetic_in_line(self):
        work_mode = {"dominant": {"id": "Prompt-Iterate", "line": "..."}}
        dims = {
            "signal_clarity": {"score": 70, "weight": 0.18},
            "recovery_velocity": {"score": 60, "weight": 0.15},
            "build_stability": {"score": 50, "weight": 0.22},
            "decision_weight": {"score": 40, "weight": 0.18},
            "context_command": {"score": 30, "weight": 0.12},
            "orchestration_range": {"score": 20, "weight": 0.15},
        }
        line = build_summary_line(work_mode, dims, {"totalSessions": 10})
        assert "<synthetic>" not in line


# ── AI leverage signal (measured facts + labeled estimate band) ─────────────


class TestLeverageSignal:
    def _cursor(self, commits=265, ai=132606, human=1725):
        return {
            "scored_commits": {
                "totalCommits": commits,
                "totalAiLines": ai,
                "totalHumanLines": human,
            }
        }

    def test_measured_facts(self):
        from nextmillionai.aggregator import build_leverage_signal

        lev = build_leverage_signal(self._cursor(), {"totalEstimatedHours": 897.0})
        assert lev["aiShare"] == 98.7
        assert lev["outputMultiple"] == 50.0  # capped display
        assert lev["outputMultipleCapped"] is True
        assert lev["soloEquivalentHours"] == {"low": 1193, "high": 1794}
        assert "estimate" in lev["estimateNote"].lower()
        assert "265 tracked commits" in lev["basis"]

    def test_uncapped_multiple(self):
        from nextmillionai.aggregator import build_leverage_signal

        lev = build_leverage_signal(
            self._cursor(commits=50, ai=3000, human=1000), {"totalEstimatedHours": 100}
        )
        assert lev["aiShare"] == 75.0
        assert lev["outputMultiple"] == 4.0
        assert lev["outputMultipleCapped"] is False

    def test_all_ai_lines_no_silly_ratio(self):
        from nextmillionai.aggregator import build_leverage_signal

        lev = build_leverage_signal(
            self._cursor(commits=50, ai=5000, human=0), {"totalEstimatedHours": 100}
        )
        assert lev["aiShare"] == 100.0
        assert lev["outputMultiple"] is None  # never a fabricated ratio

    def test_thin_data_is_insufficient(self):
        from nextmillionai.aggregator import build_leverage_signal

        assert build_leverage_signal(self._cursor(commits=5), {}) is None
        assert build_leverage_signal(self._cursor(commits=50, ai=300, human=100), {}) is None
        assert build_leverage_signal(None, {"totalEstimatedHours": 100}) is None

    def test_no_hours_no_counterfactual(self):
        from nextmillionai.aggregator import build_leverage_signal

        lev = build_leverage_signal(self._cursor(), {})
        assert lev is not None  # measured facts still stand
        assert lev["soloEquivalentHours"] is None  # estimate needs hours


class TestProvenanceSourceStates:
    """WS1: every consent/detection state must read accurately in the
    coverage sources Provenance renders."""

    def _cov(self, enabled, detected, raw):
        from nextmillionai.aggregator import build_coverage_report

        return {
            s["id"]: s for s in build_coverage_report(enabled, {}, detected, raw, None)["sources"]
        }

    def test_desktop_consented_and_collected(self):
        s = self._cov(
            {"claude_desktop": True},
            {"claude_desktop": True},
            {"claude_desktop": {"mcpServerCount": 1}},
        )["claude_desktop"]
        assert s["consented"] and s["collected"] and s["detectedOnMachine"]

    def test_desktop_present_but_unconsented_is_a_gap(self):
        from nextmillionai.aggregator import build_coverage_report

        rep = build_coverage_report(
            {"claude_desktop": False},
            {},
            {"claude_desktop": True},
            {"claude_desktop": None},
            None,
        )
        s = {x["id"]: x for x in rep["sources"]}["claude_desktop"]
        assert s["detectedOnMachine"] and not s["consented"] and not s["collected"]
        assert any(g["source"] == "claude_desktop" for g in rep["gaps"])

    def test_consented_but_empty_reads_as_no_data(self):
        s = self._cov({"claude_desktop": True}, {"claude_desktop": True}, {"claude_desktop": None})[
            "claude_desktop"
        ]
        assert s["consented"] and s["detectedOnMachine"] and not s["collected"]

    def test_toggle_roundtrip(self, tmp_path, monkeypatch):
        from nextmillionai.consent import load_consent, save_consent

        monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path))
        for value in (True, False, True):
            sources = dict(load_consent()["sources"]) if load_consent() else {}
            sources["claude_desktop"] = value
            save_consent(sources)
            assert load_consent()["sources"]["claude_desktop"] is value


# ── Session-metric fold ──────────────────────────────────────────────────────


def _kiro_session(
    sid: str,
    *,
    user_msgs: int = 0,
    word_counts: list[int] | None = None,
    tools: dict[str, int] | None = None,
    models: list[str] | None = None,
    extras: dict | None = None,
) -> Session:
    return Session(
        tool="kiro",
        session_id=sid,
        project_path="/Users/dev/proj",
        started_at=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 7, 1, 11, 0, tzinfo=timezone.utc),
        user_msgs=user_msgs,
        assistant_msgs=user_msgs,
        tool_calls_by_type=dict(tools or {}),
        models=list(models or []),
        prompt_word_counts=list(word_counts or []),
        extras=dict(extras or {}),
    )


class TestFoldSessionMetrics:
    """fold_session_metrics: deep non-claude/cursor sessions feed the
    measured metrics with the exact same math as compute_normalized."""

    def _claude_raw(self) -> dict:
        # 2 sessions, 4 user messages, 60 words total
        return {
            "sessions": [
                {"userMessages": 3, "userWordCount": 45},
                {"userMessages": 1, "userWordCount": 15},
            ],
            "models_used": {"claude-sonnet-4": 10},
        }

    def test_noop_when_nothing_to_fold(self):
        """Claude/cursor-only profiles stay bit-identical."""
        from nextmillionai.aggregator import fold_session_metrics

        normalized = {"avgPromptWords": 15, "avgTurnsPerTask": 2.0, "mcpToolCalls": 3}
        before = dict(normalized)
        claude_only = Session(tool="claude_code", session_id="c1")
        cursor_only = Session(tool="cursor", session_id="x1")
        fold_session_metrics(normalized, [claude_only, cursor_only], self._claude_raw(), None)
        assert normalized == before

    def test_weighted_average_merge(self):
        """Merged averages recomputed from raw sums, matching the base formulas."""
        from nextmillionai.aggregator import fold_session_metrics

        normalized = {"avgTurnsPerTask": 2.0, "avgPromptWords": 15, "avgPromptsPerSession": 2.0}
        kiro = _kiro_session("k1", user_msgs=2, word_counts=[10, 30])
        fold_session_metrics(normalized, [kiro], self._claude_raw(), None)
        # turns: (4 claude user + 2 kiro user) / (2 claude sessions + 1 kiro) = 2.0
        assert normalized["avgTurnsPerTask"] == 2.0
        assert normalized["avgPromptsPerSession"] == 2.0
        # words: (60 claude + 40 kiro) / (4 + 2 user msgs) = 100/6 = 17
        assert normalized["avgPromptWords"] == 17

    def test_kiro_only_sets_averages(self):
        """A kiro-only profile gets measured averages (no claude data)."""
        from nextmillionai.aggregator import fold_session_metrics

        normalized: dict = {}
        kiro = _kiro_session("k1", user_msgs=4, word_counts=[10, 10, 10, 30])
        fold_session_metrics(normalized, [kiro], None, None)
        assert normalized["avgTurnsPerTask"] == 4.0
        assert normalized["avgPromptWords"] == 15

    def test_subagent_prompts_excluded_from_averages(self):
        """Subagent sessions carry orchestrator prompts — never in averages,
        but their terminal commands still count."""
        from nextmillionai.aggregator import fold_session_metrics

        normalized: dict = {}
        parent = _kiro_session("k1", user_msgs=2, word_counts=[10, 10])
        sub = _kiro_session(
            "k2",
            user_msgs=5,
            word_counts=[100] * 5,
            tools={"shell": 3},
            extras={"is_subagent": True, "parent_session_id": "k1"},
        )
        fold_session_metrics(normalized, [parent, sub], None, None)
        assert normalized["avgTurnsPerTask"] == 2.0  # only the parent
        assert normalized["avgPromptWords"] == 10
        assert normalized["terminalCommandCount"] == 3  # subagent shell counts

    def test_terminal_alias_shell(self):
        from nextmillionai.aggregator import fold_session_metrics

        normalized = {"terminalCommandCount": 5}
        kiro = _kiro_session("k1", user_msgs=1, word_counts=[5], tools={"shell": 2, "read": 4})
        fold_session_metrics(normalized, [kiro], None, None)
        assert normalized["terminalCommandCount"] == 7

    def test_mcp_declared_by_adapter_wins(self):
        from nextmillionai.aggregator import fold_session_metrics

        normalized: dict = {}
        kiro = _kiro_session(
            "k1",
            user_msgs=1,
            word_counts=[5],
            tools={"jira": 4, "shell": 1},
            extras={"mcpToolCalls": 4},
        )
        fold_session_metrics(normalized, [kiro], None, None)
        assert normalized["mcpToolCalls"] == 4

    def test_mcp_marker_fallback(self):
        from nextmillionai.aggregator import fold_session_metrics

        normalized: dict = {}
        other = Session(
            tool="somecli",
            session_id="s1",
            user_msgs=1,
            tool_calls_by_type={"mcp__jira__search": 2, "bash": 1},
        )
        fold_session_metrics(normalized, [other], None, None)
        assert normalized["mcpToolCalls"] == 2

    def test_model_union(self):
        from nextmillionai.aggregator import fold_session_metrics

        normalized = {"modelCount": 1}
        kiro = _kiro_session(
            "k1", user_msgs=1, word_counts=[5], models=["Claude Sonnet 4", "claude-sonnet-4"]
        )
        fold_session_metrics(normalized, [kiro], self._claude_raw(), None)
        # claude-sonnet-4 (raw) ∪ {Claude Sonnet 4, claude-sonnet-4} = 2 labels
        assert normalized["modelCount"] == 2

    def test_tool_count_bumps(self):
        from nextmillionai.aggregator import fold_session_metrics

        normalized = {"uniqueToolCount": 2, "cliAiToolCount": 1}
        kiro = _kiro_session("k1", user_msgs=1, word_counts=[5], tools={"shell": 1})
        fold_session_metrics(normalized, [kiro], None, None)
        assert normalized["uniqueToolCount"] == 3
        assert normalized["cliAiToolCount"] == 2

    def test_ide_only_kiro_is_not_a_cli_surface(self):
        from nextmillionai.aggregator import fold_session_metrics

        normalized = {"uniqueToolCount": 2, "cliAiToolCount": 1}
        ide = _kiro_session("k1", user_msgs=1, word_counts=[5], extras={"source": "ide"})
        fold_session_metrics(normalized, [ide], None, None)
        assert normalized["uniqueToolCount"] == 3  # still a surface
        assert normalized["cliAiToolCount"] == 1  # not a CLI one

    def test_codex_sessions_never_double_count_tool_totals(self):
        """codex is already in compute_normalized's tools_detected — the
        fold must not bump uniqueToolCount/cliAiToolCount for it again."""
        from nextmillionai.aggregator import fold_session_metrics

        normalized = {"uniqueToolCount": 2, "cliAiToolCount": 2}
        codex = Session(tool="codex", session_id="c1", user_msgs=2, prompt_word_counts=[7, 9])
        fold_session_metrics(normalized, [codex], None, None)
        assert normalized["uniqueToolCount"] == 2
        assert normalized["cliAiToolCount"] == 2
        # but its prompts DO feed the averages (declared in signal_registry)
        assert normalized["avgPromptWords"] == 8


class TestAttributeSubagentDispatches:
    def test_parent_credited(self):
        from nextmillionai.aggregator import attribute_subagent_dispatches

        parent = _kiro_session("k1", user_msgs=2)
        c1 = _kiro_session("k2", extras={"is_subagent": True, "parent_session_id": "k1"})
        c2 = _kiro_session("k3", extras={"is_subagent": True, "parent_session_id": "k1"})
        attribute_subagent_dispatches([parent, c1, c2])
        assert parent.tool_calls_by_type["task"] == 2

    def test_max_guards_double_recording(self):
        from nextmillionai.aggregator import attribute_subagent_dispatches

        parent = _kiro_session("k1", user_msgs=2, tools={"task": 5})
        child = _kiro_session("k2", extras={"is_subagent": True, "parent_session_id": "k1"})
        attribute_subagent_dispatches([parent, child])
        assert parent.tool_calls_by_type["task"] == 5

    def test_missing_parent_never_invents(self):
        from nextmillionai.aggregator import attribute_subagent_dispatches

        orphan = _kiro_session("k9", extras={"is_subagent": True, "parent_session_id": "gone"})
        sessions = [orphan]
        attribute_subagent_dispatches(sessions)
        assert "task" not in orphan.tool_calls_by_type

    def test_claude_sessions_untouched(self):
        from nextmillionai.aggregator import attribute_subagent_dispatches

        claude = Session(tool="claude_code", session_id="c1", tool_calls_by_type={"task": 3})
        attribute_subagent_dispatches([claude])
        assert claude.tool_calls_by_type["task"] == 3
