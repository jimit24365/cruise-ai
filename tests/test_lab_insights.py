"""Tests for the Lab insight engine (build_experimental_signals v2).

Admission rule under test: cards say something the main page can't
(patterns, tensions, gaps), thin data emits nothing (insufficiency over
estimation), and wrapped-card stats are not restated.
"""

from datetime import datetime, timedelta

from nextmillionai.adapters._base import Session
from nextmillionai.aggregator import build_experimental_signals, build_scanned_projects


def make_sessions(
    n=20,
    start=None,
    project="/tmp/proj",
    words=100,
    msgs=8,
    tools=None,
    months_spread=3,
    model="claude-x",
):
    start = start or datetime(2026, 1, 5, 10, 0)
    sessions = []
    for i in range(n):
        t = start + timedelta(days=(i * months_spread * 30) // max(n, 1))
        sessions.append(
            Session(
                tool="claude_code",
                session_id=f"s{i}",
                project_path=project,
                started_at=t,
                ended_at=t + timedelta(minutes=40),
                user_msgs=msgs,
                assistant_msgs=msgs,
                tool_calls_by_type=dict(tools or {"file": 3, "terminal": 1}),
                models=[model],
                prompt_word_counts=[words] * msgs,
            )
        )
    return sessions


def labels(result):
    return [s["label"] for s in result["signals"]]


class TestAdmissionRule:
    def test_no_restated_wrapped_stats(self):
        result = build_experimental_signals(
            {
                "totalSessions": 20,
                "maxParallelAgents": 2,
                "deepSessionCount": 5,
                "planModePercent": 50,
                "featureToFixRatio": 3.0,
            },
            sessions=make_sessions(20),
        )
        got = labels(result)
        for restated in (
            "Max parallel agents",
            "Deep sessions",
            "Plan mode",
            "Feature vs fix ratio",
        ):
            assert restated not in got

    def test_thin_data_emits_nothing(self):
        result = build_experimental_signals({"totalSessions": 2}, sessions=make_sessions(2))
        # Below thresholds: no funnel, no series cards — honesty over coverage
        assert result["signals"] == []
        assert result["available"] is False


class TestFunnelAndSeries:
    def test_delegation_funnel_emitted(self):
        result = build_experimental_signals(
            {"totalSessions": 20, "maxParallelAgents": 2},
            sessions=make_sessions(20),
        )
        funnel = next(s for s in result["signals"] if s["label"] == "Delegation funnel")
        assert "two parallel agents" in funnel["headline"]
        assert funnel["kind"] == "measured"

    def test_prompt_evolution_has_series(self):
        sessions = make_sessions(15, words=100, months_spread=3) + make_sessions(
            15, start=datetime(2026, 4, 5), words=300, months_spread=2
        )
        result = build_experimental_signals({"totalSessions": 30}, sessions=sessions)
        evo = next(s for s in result["signals"] if s["label"] == "Prompt evolution")
        assert len(evo["series"]) >= 2
        assert len(evo["seriesLabels"]) == len(evo["series"])
        assert "rising" in evo["headline"]

    def test_session_rhythm_series_capped(self):
        sessions = make_sessions(60, months_spread=12)
        result = build_experimental_signals({"totalSessions": 60}, sessions=sessions)
        rhythm = next(s for s in result["signals"] if s["label"] == "Session rhythm")
        assert len(rhythm["series"]) <= 26


class TestTensionCards:
    def _git(self, n_repos, scaffolded):
        projects = []
        for i in range(n_repos):
            tools = ["CLAUDE.md"] if i < scaffolded else []
            projects.append(
                {
                    "path": f"/r{i}",
                    "tools": tools,
                    "languages": [],
                    "frameworks": [],
                    "commits_6m": 1,
                }
            )
        return {"projects": projects}

    def test_context_tension_when_no_scaffolding(self):
        result = build_experimental_signals(
            {"totalSessions": 20, "referenceUsageRate": 0.6},
            git_data=self._git(5, scaffolded=0),
            sessions=make_sessions(20),
        )
        assert "Context tension" in labels(result)

    def test_scaffolding_card_when_present(self):
        result = build_experimental_signals(
            {"totalSessions": 20, "referenceUsageRate": 0.6},
            git_data=self._git(5, scaffolded=2),
            sessions=make_sessions(20),
        )
        card = next(s for s in result["signals"] if s["label"] == "Context scaffolding")
        assert "2 of 5" in card["headline"]


class TestSelfTrends:
    def test_meaningful_delta_emits_card(self):
        result = build_experimental_signals(
            {"totalSessions": 20, "recentModelCount": 4, "historicalModelCount": 2},
            sessions=make_sessions(20),
        )
        card = next(s for s in result["signals"] if s["label"] == "Model range trend")
        assert "vs your history" in card["headline"]
        assert "no cohort" in card["detail"]

    def test_small_delta_emits_nothing(self):
        result = build_experimental_signals(
            {"totalSessions": 20, "recentModelCount": 2.1, "historicalModelCount": 2},
            sessions=make_sessions(20),
        )
        assert "Model range trend" not in labels(result)


class TestProjectSeries:
    def test_scanned_projects_carry_activity_series(self):
        sessions = make_sessions(10, project="/a", months_spread=4) + make_sessions(
            4, project="/b", months_spread=1
        )
        projects = build_scanned_projects(sessions)
        by_name = {p["name"]: p for p in projects}
        assert "series" in by_name["a"]
        assert len(by_name["a"]["series"]) <= 12
        # Shared month axis: both projects have equal-length series
        assert len(by_name["a"]["series"]) == len(by_name["b"]["series"])
        assert sum(by_name["a"]["series"]) == 10


class TestHarnessSummary:
    def test_harness_totals_from_repos_and_sessions(self):
        from nextmillionai.aggregator import build_harness_summary

        git_data = {
            "projects": [
                {
                    "tools": ["CLAUDE.md", "Skills", "MCP"],
                    "harness": {
                        "skills": 4,
                        "agents": 2,
                        "commands": 3,
                        "hooks": 1,
                        "rules": 0,
                        "claudeMdLines": 120,
                    },
                },
                {"tools": [], "harness": {}},
            ]
        }
        sessions = make_sessions(5, tools={"task": 3, "file": 2}) + make_sessions(5)
        h = build_harness_summary(git_data, sessions)
        assert h["skills"] == 4 and h["agents"] == 2 and h["commands"] == 3
        assert h["claudeMdRepos"] == 1 and h["claudeMdLines"] == 120
        assert h["scaffoldedRepos"] == 1 and h["totalRepos"] == 2
        assert h["subagentDispatches"] == 15
        assert h["sessionsWithSubagents"] == 5
        assert h["available"] is True

    def test_funnel_reports_subagent_dispatches(self):
        sessions = make_sessions(20, tools={"file": 2, "task": 1})
        result = build_experimental_signals({"totalSessions": 20}, sessions=sessions)
        funnel = next(s for s in result["signals"] if s["label"] == "Delegation funnel")
        assert "dispatches subagents" in funnel["headline"]
        assert "20 dispatches" in funnel["detail"]

    def test_harness_inventory_card(self):
        from nextmillionai.aggregator import build_experimental_signals as bes

        git_data = {
            "projects": [
                {
                    "tools": ["Skills"],
                    "harness": {
                        "skills": 6,
                        "agents": 0,
                        "commands": 0,
                        "hooks": 2,
                        "rules": 0,
                        "claudeMdLines": 0,
                    },
                    "frameworks": [],
                    "languages": [],
                    "commits_6m": 1,
                }
            ]
        }
        result = bes({"totalSessions": 20}, git_data=git_data, sessions=make_sessions(20))
        card = next(s for s in result["signals"] if s["label"] == "Harness inventory")
        assert "6 skills" in card["headline"]


class TestConfidence:
    def test_confidence_varies_with_data(self):
        from nextmillionai.aggregator import build_confidence

        # Thin: one source, tiny sample, every dimension on a small sample.
        thin_dims = {k: {"score": 50, "provisional": True} for k in ("a", "b")}
        sparse = build_confidence(
            {"a": 1}, ["Claude Code"], 5, 8, dims=thin_dims, active_hours=2, active_days=3
        )
        # Rich: full slots, all sources, real hours/days, every dimension sufficient.
        rich_dims = {f"d{i}": {"score": 70, "provisional": False} for i in range(6)}
        rich = build_confidence(
            {f"k{i}": 1 for i in range(46)},
            ["a", "b", "c", "d"],
            365,
            200,
            dims=rich_dims,
            active_hours=60,
            active_days=120,
        )
        assert sparse["score"] < 30
        assert rich["score"] >= 90
        assert sparse["score"] != rich["score"]

    def test_mark_dimension_sufficiency_flags_small_samples(self):
        from nextmillionai.aggregator import mark_dimension_sufficiency

        dims = {
            "build_stability": {"score": 82},  # 7 commits -> provisional
            "signal_clarity": {"score": 72},  # 106 sessions -> sufficient
            "decision_weight": {"score": 50},  # 5 plans -> provisional
        }
        mark_dimension_sufficiency(
            dims, {"totalSessions": 106}, {"scored_commits": 7, "architecture_plans": 5}
        )
        assert dims["build_stability"]["provisional"] is True
        assert dims["build_stability"]["sampleSize"] == 7
        assert dims["signal_clarity"]["provisional"] is False
        assert dims["decision_weight"]["provisional"] is True
        # the score itself is never touched
        assert dims["build_stability"]["score"] == 82

    def test_provisional_dimensions_hold_confidence_down(self):
        from nextmillionai.aggregator import build_confidence

        same = dict(active_hours=60, active_days=120)
        base = {f"k{i}": 1 for i in range(46)}
        all_ok = {f"d{i}": {"score": 70, "provisional": False} for i in range(6)}
        half = {f"d{i}": {"score": 70, "provisional": i < 3} for i in range(6)}
        # Same breadth/hours/days, but half the dimensions on small samples → lower.
        assert (
            build_confidence(base, ["a", "b", "c", "d"], 365, 200, dims=half, **same)["score"]
            < build_confidence(base, ["a", "b", "c", "d"], 365, 200, dims=all_ok, **same)["score"]
        )

    def test_confidence_never_pinned_at_100(self):
        from nextmillionai.aggregator import build_confidence

        maximal = build_confidence(
            {f"k{i}": 1 for i in range(60)},
            ["a", "b", "c", "d"],
            999,
            999,
            dims={f"d{i}": {"score": 90, "provisional": False} for i in range(6)},
            active_hours=999,
            active_days=999,
            code_scan_ran=True,
        )
        assert maximal["score"] <= 98

    def test_factors_carry_explanations(self):
        from nextmillionai.aggregator import build_confidence

        conf = build_confidence({"a": 1}, ["Claude Code"], 29, 155)
        for factor in ("completeness", "sources", "volume", "window"):
            assert "detail" in conf["factors"][factor]
