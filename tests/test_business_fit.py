"""Tests for the Business Fit Map (fit-to-context, never ranking) and
the positioning footprint.

Values under test: formulas trace to archetype scores only; zones carry
category examples, never company names; insufficient data -> no map;
fit framing language present.
"""

import json

from cruise_ai.business_fit import (
    BUSINESS_ZONES,
    build_business_fit,
    compute_map_position,
    compute_zone_affinity,
)
from cruise_ai.scoring import compute_positioning


def arch(id_, score):
    return {"id": id_, "score": score}


ALL_HIGH = [
    arch(a, 90)
    for a in (
        "agent_builder",
        "multi_agent_orchestrator",
        "integration_architect",
        "context_engineer",
        "system_thinker",
        "rapid_prototyper",
        "code_weaver",
        "automation_engineer",
        "cli_native",
    )
]


class TestZoneData:
    def test_no_company_names_anywhere(self):
        dumped = json.dumps(BUSINESS_ZONES).lower()
        for company in (
            "cursor",
            "harvey",
            "ramp",
            "anthropic",
            "openai",
            "anysphere",
            "perplexity",
            "notion",
            "salesforce",
        ):
            assert company not in dumped, f"company name leaked: {company}"

    def test_every_zone_has_categories(self):
        for z in BUSINESS_ZONES:
            assert z["categories"], z["id"]
            assert "fitRequirements" in z

    def test_requirement_weights_sum_to_one(self):
        for z in BUSINESS_ZONES:
            total = sum(r["weight"] for r in z["fitRequirements"])
            assert abs(total - 1.0) < 0.001, f"{z['id']} weights sum {total}"


class TestMapPosition:
    def test_balanced_profile_centers(self):
        pos = compute_map_position(ALL_HIGH)
        assert -0.2 <= pos["x"] <= 0.2
        assert -0.2 <= pos["y"] <= 0.2

    def test_ai_native_builder_moves_right(self):
        archetypes = [
            arch("agent_builder", 95),
            arch("multi_agent_orchestrator", 90),
            arch("integration_architect", 85),
            arch("context_engineer", 80),
            arch("system_thinker", 80),
            arch("rapid_prototyper", 20),
            arch("code_weaver", 20),
            arch("automation_engineer", 20),
            arch("cli_native", 20),
        ]
        assert compute_map_position(archetypes)["x"] > 0.3

    def test_orchestrator_contributes_to_ai_native(self):
        base = [arch("multi_agent_orchestrator", 0)]
        boosted = [arch("multi_agent_orchestrator", 100)]
        assert compute_map_position(boosted)["x"] > compute_map_position(base)["x"]

    def test_bounds(self):
        pos = compute_map_position(ALL_HIGH)
        assert -1 <= pos["x"] <= 1 and -1 <= pos["y"] <= 1


class TestZoneAffinity:
    def test_strong_fit_when_all_minimums_met(self):
        zone = BUSINESS_ZONES[0]
        result = compute_zone_affinity(ALL_HIGH, zone)
        assert result["isStrongFit"]
        assert result["percentage"] == 100
        assert result["gaps"] == []

    def test_gaps_reported_with_required_vs_actual(self):
        weak = [arch("agent_builder", 40)]
        zone = next(z for z in BUSINESS_ZONES if z["id"] == "dev_tools")
        result = compute_zone_affinity(weak, zone)
        assert not result["isStrongFit"]
        gap = next(g for g in result["gaps"] if g["archetypeId"] == "agent_builder")
        assert gap["required"] == 85 and gap["actual"] == 40

    def test_partial_capped_per_requirement(self):
        # One archetype far above min must not compensate beyond its weight
        over = [arch("agent_builder", 100)]
        zone = next(z for z in BUSINESS_ZONES if z["id"] == "dev_tools")
        result = compute_zone_affinity(over, zone)
        assert result["percentage"] <= 35 + 1  # only agent_builder's weight


class TestBuildBusinessFit:
    def test_insufficient_data_returns_none(self):
        assert build_business_fit([]) is None
        assert build_business_fit([arch("agent_builder", 0)]) is None

    def test_full_output_shape_and_framing(self):
        fit = build_business_fit(ALL_HIGH)
        assert set(fit["axes"]["x"]) == {"AI-Augmented", "AI-Native"}
        assert len(fit["zones"]) == len(BUSINESS_ZONES)
        assert len(fit["topFits"]) == 3
        assert "not a ranking" in fit["framing"]
        # Zones sorted by affinity descending
        affs = [z["affinity"] for z in fit["zones"]]
        assert affs == sorted(affs, reverse=True)

    def test_requirements_expose_actuals(self):
        fit = build_business_fit(ALL_HIGH)
        for z in fit["zones"]:
            for r in z["requirements"]:
                assert "actual" in r and "minScore" in r


class TestPositioningFootprint:
    def _git(self):
        return {
            "projects": [
                {
                    "path": "/a",
                    "frameworks": ["LangChain"],
                    "tools": ["CLAUDE.md"],
                    "languages": ["Python"],
                    "commits_6m": 30,
                },
                {
                    "path": "/b",
                    "frameworks": [],
                    "tools": [],
                    "languages": ["TypeScript"],
                    "commits_6m": 60,
                },
                {
                    "path": "/c",
                    "frameworks": ["Anthropic"],
                    "tools": ["MCP"],
                    "languages": ["Python"],
                    "commits_6m": 10,
                },
            ]
        }

    def test_footprint_is_a_distribution(self):
        pos = compute_positioning({"mcpServerCount": 1}, git_data=self._git())
        fp = pos["footprint"]
        assert len(fp["cells"]) >= 2  # multiple cells, not a single verdict
        assert abs(sum(c["weight"] for c in fp["cells"]) - 100) <= len(fp["cells"])
        dominant = fp["cells"][0]
        assert dominant["weight"] >= fp["cells"][-1]["weight"]

    def test_cells_carry_domain_stage_projects(self):
        pos = compute_positioning({}, git_data=self._git())
        for c in pos["footprint"]["cells"]:
            assert c["domain"] in ("products", "ai_products", "ai_systems")
            assert c["stage"] in ("prompting", "harnessing", "designs_the_loop")
            assert c["projects"] >= 0

    def test_no_git_no_footprint(self):
        pos = compute_positioning({}, git_data=None)
        assert "footprint" not in pos


class TestHonestMapLabels:
    def test_map_axes_match_their_math(self):
        from cruise_ai.scoring import score_profile

        profile = score_profile({"normalized": {"totalSessions": 20}})
        m = profile["map"]
        assert m["xLabel"] == ["Explorer", "Architect"]
        assert m["yLabel"] == ["Solo", "Orchestrator"]
        # The old dishonest relabel must be gone
        assert "AI Systems" not in json.dumps(m)


class TestLoopEvidence:
    """Subagent dispatches and per-repo orchestration must reach
    the leverage stage and the footprint — directing a fleet IS
    designing the loop."""

    def test_dispatches_qualify_designs_the_loop(self):
        pos = compute_positioning(
            {"subagentDispatches": 65, "sessionsWithSubagents": 11, "maxParallelAgents": 2}
        )
        assert pos["leverageMode"]["current"] == "designs_the_loop"
        assert pos["leverageMode"]["subFlavor"] == "orchestrating"
        assert any("65 subagent dispatches" in e for e in pos["leverageMode"]["evidence"])

    def test_few_dispatches_do_not_qualify(self):
        pos = compute_positioning({"subagentDispatches": 4, "sessionsWithSubagents": 1})
        assert pos["leverageMode"]["current"] == "prompting"

    def test_footprint_repo_with_dispatches_is_loop_stage(self):
        git = {
            "projects": [
                {
                    "path": "/loops",
                    "frameworks": [],
                    "tools": [],
                    "languages": [],
                    "commits_6m": 10,
                },
                {
                    "path": "/plain",
                    "frameworks": [],
                    "tools": [],
                    "languages": [],
                    "commits_6m": 10,
                },
            ]
        }
        orch = {"/loops": {"dispatches": 12, "maxParallel": 1, "sessionsWithDispatch": 4}}
        pos = compute_positioning({}, git_data=git, project_orchestration=orch)
        stages = {c["domain"] + "|" + c["stage"]: c for c in pos["footprint"]["cells"]}
        assert "products|designs_the_loop" in stages
        assert "products|prompting" in stages

    def test_project_orchestration_builder(self):
        from datetime import datetime, timedelta

        from cruise_ai.adapters._base import Session
        from cruise_ai.aggregator import build_project_orchestration

        t0 = datetime(2026, 6, 1, 10, 0)
        sessions = [
            Session(
                tool="claude_code",
                session_id="a",
                project_path="/p",
                started_at=t0,
                ended_at=t0 + timedelta(hours=2),
                tool_calls_by_type={"task": 5},
            ),
            Session(
                tool="claude_code",
                session_id="b",
                project_path="/p",
                started_at=t0 + timedelta(minutes=30),
                ended_at=t0 + timedelta(hours=1),
            ),
            Session(
                tool="claude_code",
                session_id="c",
                project_path="/q",
                started_at=t0,
                ended_at=t0 + timedelta(minutes=10),
            ),
        ]
        orch = build_project_orchestration(sessions)
        assert orch["/p"]["dispatches"] == 5
        assert orch["/p"]["maxParallel"] == 2  # a and b overlap
        assert "/q" not in orch  # no loop evidence there
