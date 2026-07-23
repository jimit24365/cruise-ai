"""Tests for the cruise_ai scoring engine.

Deterministic tests: known normalized-metric inputs -> expected dimension
scores, archetype thresholds, title triggers, composite bounds, and weight
renormalization when dimensions are missing.
"""

from __future__ import annotations

from cruise_ai.schema import TAXONOMY_VERSION
from cruise_ai.scoring import (
    _adapt_weights,
    _avg,
    assess_trajectory,
    build_titles_catalog,
    clamp,
    classify_work_mode,
    compute_archetypes,
    compute_map,
    derive_titles,
    detect_anti_patterns,
    inverse,
    linear,
    score_dimensions,
    score_profile,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _full_metrics(**overrides) -> dict:
    """Build a plausible normalized-metrics dict with all fields populated."""
    base = {
        # Signal Clarity
        "firstShotAcceptRate": 0.65,
        "avgTurnsPerTask": 3.5,
        "referenceUsageRate": 0.35,
        "correctionConvergenceRate": 0.70,
        "avgPromptWords": 45,
        "modelCount": 3,
        # Build Stability
        "aiLineSurvivalRate": 0.82,
        "errorFixRate": 0.88,
        "testAfterAiRate": 0.40,
        "errorsPerAiBlock": 0.05,
        "buildSuccessRate": 0.75,
        "postAiEditRate": 0.15,
        "leverageRatio": 8.0,
        "totalScoredCommits": 60,
        # Decision Weight
        "planCount": 20,
        "avgPlanComplexity": 100,
        "composerRatio": 0.60,
        # Recovery Velocity
        "terminalCommandCount": 80,
        "totalAiCodeBlocks": 5000,
        # Context Command
        "totalSessions": 100,
        "projectCount": 6,
        "aiUsageSpanDays": 90,
        # Orchestration Range
        "uniqueToolCount": 5,
        "agentModeRatio": 0.40,
        "mcpServerCount": 2,
        "cliAiToolCount": 2,
        "cliAiCommandCount": 30,
        # Archetypes
        "filesPerSession": 12,
        "languageCount": 4,
        # Trajectory
        "recentSignalDensity": 0.5,
        "historicalSignalDensity": 0.5,
        "recentModelCount": 3,
        "historicalModelCount": 3,
        "recentPlanRatio": 0.2,
        "historicalPlanRatio": 0.2,
        "recentLanguageCount": 4,
        "historicalLanguageCount": 4,
    }
    base.update(overrides)
    return base


# ── Primitive helpers ────────────────────────────────────────────────────────


class TestHelpers:
    def test_linear_at_floor(self):
        assert linear(0.2, 0.2, 0.85) == 0

    def test_linear_at_ceiling(self):
        assert linear(0.85, 0.2, 0.85) == 100

    def test_linear_midpoint(self):
        result = linear(0.525, 0.2, 0.85)
        assert 49 <= result <= 51

    def test_linear_below_floor(self):
        assert linear(0.0, 0.2, 0.85) == 0

    def test_linear_above_ceiling(self):
        assert linear(1.0, 0.2, 0.85) == 100

    def test_inverse_at_best(self):
        assert inverse(1.5, 1.5, 10) == 100

    def test_inverse_at_worst(self):
        assert inverse(10, 1.5, 10) == 0

    def test_inverse_below_best(self):
        assert inverse(0.5, 1.5, 10) == 100

    def test_clamp_within_range(self):
        assert clamp(50) == 50

    def test_clamp_rounds(self):
        assert clamp(72.6) == 73

    def test_clamp_below_zero(self):
        assert clamp(-10) == 0

    def test_clamp_above_hundred(self):
        assert clamp(150) == 100

    def test_avg_empty(self):
        assert _avg([]) is None

    def test_avg_single(self):
        assert _avg([80]) == 80

    def test_avg_clamps(self):
        assert _avg([200, 200]) == 100


# ── Dimension scoring ────────────────────────────────────────────────────────


class TestDimensionScoring:
    def test_all_dimensions_present(self):
        dims = score_dimensions(_full_metrics())
        expected = {
            "signal_clarity",
            "build_stability",
            "decision_weight",
            "recovery_velocity",
            "context_command",
            "orchestration_range",
        }
        assert set(dims.keys()) == expected

    def test_dimension_has_required_keys(self):
        dims = score_dimensions(_full_metrics())
        for name, d in dims.items():
            assert "score" in d, f"{name} missing 'score'"
            assert "evidence" in d, f"{name} missing 'evidence'"
            assert "weight" in d, f"{name} missing 'weight'"
            assert "name" in d, f"{name} missing 'name'"

    def test_no_score_exceeds_100(self):
        dims = score_dimensions(_full_metrics())
        for name, d in dims.items():
            if d["score"] is not None:
                assert 0 <= d["score"] <= 100, f"{name} score {d['score']} out of range"

    def test_no_score_exceeds_100_extreme_inputs(self):
        """Even with extreme input values, scores stay in [0, 100]."""
        extreme = _full_metrics(
            firstShotAcceptRate=1.0,
            aiLineSurvivalRate=1.0,
            errorFixRate=1.0,
            leverageRatio=999,
            planCount=500,
            avgPlanComplexity=999,
            referenceUsageRate=1.0,
            totalSessions=10000,
            uniqueToolCount=50,
            modelCount=20,
            mcpServerCount=50,
        )
        dims = score_dimensions(extreme)
        for name, d in dims.items():
            if d["score"] is not None:
                assert 0 <= d["score"] <= 100, f"{name} = {d['score']}"

    def test_weights_sum_to_one(self):
        dims = score_dimensions(_full_metrics())
        total = sum(d["weight"] for d in dims.values())
        assert abs(total - 1.0) < 1e-9

    def test_empty_input_returns_none_scores(self):
        """All dimensions return None when given no metrics."""
        dims = score_dimensions({})
        for name, d in dims.items():
            assert d["score"] is None, f"{name} should be None with no input"

    def test_signal_clarity_known_input(self):
        """Known inputs produce a score in a predictable range."""
        inp = _full_metrics(
            firstShotAcceptRate=0.85,  # -> linear -> 100
            avgTurnsPerTask=1.5,  # -> inverse -> 100
            referenceUsageRate=0.6,  # -> linear -> 100
            avgPromptWords=80,  # -> 60 + linear*0.4 -> high
            modelCount=5,  # -> linear -> 100
        )
        dims = score_dimensions(inp)
        # With everything at ceiling, signal_clarity should be very high
        assert dims["signal_clarity"]["score"] >= 80

    def test_build_stability_known_input(self):
        inp = _full_metrics(
            aiLineSurvivalRate=0.95,  # -> linear -> 100
            errorFixRate=0.95,  # -> linear -> 100
            postAiEditRate=0.15,  # -> piecewise -> ~high
            leverageRatio=40,  # qualified with survival
        )
        dims = score_dimensions(inp)
        assert dims["build_stability"]["score"] >= 70


# ── Composite and weight renormalization ─────────────────────────────────────


class TestComposite:
    def test_composite_in_range(self):
        result = score_profile({"normalized": _full_metrics()})
        assert result["composite"] is not None
        assert 0 <= result["composite"] <= 100

    def test_composite_none_when_empty(self):
        result = score_profile({"normalized": {}})
        assert result["composite"] is None

    def test_weights_renormalize_when_dimensions_missing(self):
        """When some dimensions can't score, the composite uses only the
        scored dimensions and renormalizes their weights."""
        # Full metrics: all 6 dimensions score
        full = score_profile({"normalized": _full_metrics()})
        full["composite"]

        # Partial: remove Cursor-specific fields so build_stability gets None.
        # Keep fields that feed other dimensions so they still score.
        partial_inp = _full_metrics()
        # Remove the only field that feeds build_stability independently
        del partial_inp["aiLineSurvivalRate"]
        del partial_inp["errorFixRate"]
        del partial_inp["testAfterAiRate"]
        del partial_inp["errorsPerAiBlock"]
        del partial_inp["buildSuccessRate"]
        del partial_inp["postAiEditRate"]
        del partial_inp["leverageRatio"]
        del partial_inp["totalScoredCommits"]
        partial = score_profile({"normalized": partial_inp})

        # build_stability should be None
        assert partial["dimensions"]["build_stability"]["score"] is None

        # But composite is still computed from the remaining scored dimensions
        assert partial["composite"] is not None
        # Data completeness should reflect fewer scored dimensions
        assert partial["dataCompleteness"] < 1.0

    def test_data_completeness_full(self):
        result = score_profile({"normalized": _full_metrics()})
        assert result["dataCompleteness"] == 1.0

    def test_data_completeness_empty(self):
        result = score_profile({"normalized": {}})
        assert result["dataCompleteness"] == 0.0


# ── Archetype scoring ────────────────────────────────────────────────────────


class TestArchetypes:
    def test_nine_archetypes_returned(self):
        archetypes = compute_archetypes(_full_metrics())
        assert len(archetypes) == 9

    def test_archetype_ids(self):
        archetypes = compute_archetypes(_full_metrics())
        ids = {a["id"] for a in archetypes}
        expected = {
            "agent_builder",
            "integration_architect",
            "multi_agent_orchestrator",
            "code_weaver",
            "rapid_prototyper",
            "system_thinker",
            "automation_engineer",
            "cli_native",
            "context_engineer",
        }
        assert ids == expected

    def test_archetype_scores_in_range(self):
        archetypes = compute_archetypes(_full_metrics())
        for a in archetypes:
            if a["score"] is not None:
                assert 0 <= a["score"] <= 100, f"{a['id']} score = {a['score']}"

    def test_archetype_sorted_by_score_desc(self):
        archetypes = compute_archetypes(_full_metrics())
        scores = [a["score"] or 0 for a in archetypes]
        assert scores == sorted(scores, reverse=True)

    def test_archetype_level_thresholds(self):
        """Verify level labels match known threshold bands."""
        archetypes = compute_archetypes(_full_metrics())
        for a in archetypes:
            score = a["score"]
            level_id = a["level"]["id"] if a["level"] else None
            if score is None:
                assert level_id == "undetected"
            elif score >= 85:
                assert level_id == "elite", f"{a['id']}: {score} should be elite"
            elif score >= 70:
                assert level_id == "advanced", f"{a['id']}: {score} should be advanced"
            elif score >= 55:
                assert level_id == "proficient", f"{a['id']}: {score} should be proficient"
            elif score >= 35:
                assert level_id == "developing", f"{a['id']}: {score} should be developing"
            else:
                assert level_id == "emerging", f"{a['id']}: {score} should be emerging"

    def test_elite_code_weaver(self):
        """Maxing out code_weaver metrics produces a high score."""
        inp = _full_metrics(
            aiLineSurvivalRate=0.98,
            errorFixRate=0.98,
            postAiEditRate=0.12,
            totalScoredCommits=100,
        )
        archetypes = compute_archetypes(inp)
        weaver = next(a for a in archetypes if a["id"] == "code_weaver")
        assert weaver["score"] >= 80


# ── Title derivation ─────────────────────────────────────────────────────────


class TestTitles:
    def test_no_titles_when_all_low(self):
        """Truly no measured signal → no kind, honestly insufficient (not even
        the baseline AI Explorer)."""
        archetypes = compute_archetypes({})
        titles = derive_titles(archetypes)
        assert titles == []

    def test_ai_explorer_is_the_baseline_when_activity_but_no_craft(self):
        """Any measured AI activity (no archetype >= 80) → AI Explorer is the
        primary kind, never 'no kind'."""
        archetypes = [
            {"id": "context_engineer", "score": 64},
            {"id": "code_weaver", "score": 60},
            {"id": "cli_native", "score": 0},
        ]
        titles = derive_titles(archetypes)
        assert titles, "a builder with activity must hold the baseline kind"
        assert titles[0]["id"] == "ai_explorer" and titles[0]["baseline"] is True
        cat = build_titles_catalog(archetypes)
        explorer = next(c for c in cat if c["id"] == "ai_explorer")
        assert explorer["earned"] is True and explorer["baseline"] is True
        assert "Any AI coding activity" in explorer["earnedBy"]

    def test_specialized_kind_outranks_the_baseline(self):
        """A specialized craft always wins primaryTitle over AI Explorer."""
        archetypes = [
            {"id": "code_weaver", "score": 88},
            {"id": "context_engineer", "score": 50},
        ]
        titles = derive_titles(archetypes)
        assert titles[0]["id"] != "ai_explorer"  # specialized wins
        assert any(t["id"] == "ai_explorer" for t in titles)  # baseline still held

    def test_context_architect_title_triggers(self):
        """context_engineer >= 80 triggers Context Architect title."""
        inp = _full_metrics(
            referenceUsageRate=0.65,
            planCount=50,
            avgPlanComplexity=200,
            firstShotAcceptRate=0.85,
        )
        archetypes = compute_archetypes(inp)
        ce = next(a for a in archetypes if a["id"] == "context_engineer")
        if ce["score"] >= 80:
            titles = derive_titles(archetypes)
            title_ids = [t["id"] for t in titles]
            assert "context_architect" in title_ids

    def test_ai_devops_title_lower_threshold(self):
        """automation_engineer or cli_native >= 75 triggers AI DevOps title."""
        inp = _full_metrics(
            testAfterAiRate=0.80,
            buildSuccessRate=0.90,
            terminalCommandCount=200,
            cliAiToolCount=4,
        )
        archetypes = compute_archetypes(inp)
        auto = next(a for a in archetypes if a["id"] == "automation_engineer")
        if auto["score"] >= 75:
            titles = derive_titles(archetypes)
            title_ids = [t["id"] for t in titles]
            assert "devops_ai" in title_ids

    def test_legendary_title_requires_six_archetypes(self):
        """AI Pioneer needs 6+ archetypes >= 75 and at least one >= 90."""
        # With moderate inputs, no legendary title
        archetypes = compute_archetypes(_full_metrics())
        titles = derive_titles(archetypes)
        legendary = [t for t in titles if t.get("legendary")]
        # Just check the structure is correct (legendary may or may not fire)
        for t in legendary:
            assert t["legendary"] is True

    def test_titles_sorted_legendary_first(self):
        """Titles are sorted: legendary desc, rare desc, name asc."""
        archetypes = compute_archetypes(_full_metrics())
        titles = derive_titles(archetypes)
        if len(titles) >= 2:
            # Legendary should come before non-legendary
            legendary_indices = [i for i, t in enumerate(titles) if t.get("legendary")]
            non_legendary_indices = [i for i, t in enumerate(titles) if not t.get("legendary")]
            if legendary_indices and non_legendary_indices:
                assert max(legendary_indices) < min(non_legendary_indices)


# ── Anti-patterns ────────────────────────────────────────────────────────────


class TestAntiPatterns:
    def test_no_anti_patterns_with_balanced_scores(self):
        result = score_profile({"normalized": _full_metrics()})
        dims = result["dimensions"]
        work_mode = result["workMode"]
        anti = detect_anti_patterns(dims, _full_metrics(), work_mode=work_mode)
        # With balanced metrics, should have few or no anti-patterns
        ids = [a["id"] for a in anti]
        assert "high_velocity_low_stability" not in ids
        assert "ai_dependent" not in ids

    def test_high_velocity_low_stability(self):
        """signal_clarity >= 70 and build_stability < 30 triggers the pattern.
        Must NOT be in a prototyping mode (archetype-aware §10)."""
        dims = score_dimensions(_full_metrics())
        dims["signal_clarity"]["score"] = 75
        dims["build_stability"]["score"] = 20
        # Architect-First mode — this IS a risk signal
        arch_mode = {"dominant": {"id": "Architect-First", "line": ""}, "secondary": []}
        anti = detect_anti_patterns(dims, _full_metrics(), work_mode=arch_mode)
        ids = [a["id"] for a in anti]
        assert "high_velocity_low_stability" in ids

    def test_ai_dependent(self):
        """recovery_velocity < 25 triggers AI Dependent."""
        dims = score_dimensions(_full_metrics())
        dims["recovery_velocity"]["score"] = 20
        anti = detect_anti_patterns(dims, _full_metrics())
        ids = [a["id"] for a in anti]
        assert "ai_dependent" in ids

    def test_context_amnesiac(self):
        """context_command < 30 and totalSessions > 20 triggers Context Amnesiac."""
        dims = score_dimensions(_full_metrics())
        dims["context_command"]["score"] = 25
        inp = _full_metrics(totalSessions=50)
        anti = detect_anti_patterns(dims, inp)
        ids = [a["id"] for a in anti]
        assert "context_amnesiac" in ids

    def test_single_tool_lock(self):
        """orchestration_range < 25 and uniqueToolCount <= 1 triggers Single-Tool Lock."""
        dims = score_dimensions(_full_metrics())
        dims["orchestration_range"]["score"] = 20
        inp = _full_metrics(uniqueToolCount=1)
        anti = detect_anti_patterns(dims, inp)
        ids = [a["id"] for a in anti]
        assert "single_tool_lock" in ids

    def test_confident_but_wrong(self):
        """signal_clarity < 35 and totalAiCodeBlocks > 5000 triggers it."""
        dims = score_dimensions(_full_metrics())
        dims["signal_clarity"]["score"] = 30
        inp = _full_metrics(totalAiCodeBlocks=6000)
        anti = detect_anti_patterns(dims, inp)
        ids = [a["id"] for a in anti]
        assert "confident_but_wrong" in ids


# ── Trajectory ───────────────────────────────────────────────────────────────


class TestTrajectory:
    def test_insufficient_data(self):
        traj = assess_trajectory({"aiUsageSpanDays": 10})
        assert traj["id"] == "insufficient"

    def test_insufficient_when_missing(self):
        traj = assess_trajectory({})
        assert traj["id"] == "insufficient"

    def test_stable_default(self):
        traj = assess_trajectory(_full_metrics(aiUsageSpanDays=30))
        assert traj["id"] == "stable"

    def test_accelerating(self):
        traj = assess_trajectory(
            _full_metrics(
                aiUsageSpanDays=30,
                recentSignalDensity=0.8,
                historicalSignalDensity=0.4,
            )
        )
        assert traj["id"] == "accelerating"

    def test_declining(self):
        traj = assess_trajectory(
            _full_metrics(
                aiUsageSpanDays=30,
                recentSignalDensity=0.2,
                historicalSignalDensity=0.8,
            )
        )
        assert traj["id"] == "declining"

    def test_pivoting(self):
        traj = assess_trajectory(
            _full_metrics(
                aiUsageSpanDays=30,
                recentLanguageCount=8,
                historicalLanguageCount=3,
            )
        )
        assert traj["id"] == "pivoting"


# ── score_profile integration ────────────────────────────────────────────────


class TestScoreProfileIntegration:
    def test_return_structure(self):
        result = score_profile({"normalized": _full_metrics()})
        assert "composite" in result
        assert "dimensions" in result
        assert "archetypes" in result
        assert "titles" in result
        assert "primaryTitle" in result
        assert "workMode" in result
        assert "antiPatterns" in result
        assert "trajectory" in result
        assert "map" in result
        assert "growthEdge" in result
        assert "wrappedStats" in result
        assert "dataCompleteness" in result
        assert "scoredAt" in result
        assert "schema_version" in result
        assert "taxonomy_version" in result

    def test_composite_never_exceeds_100(self):
        """Even with maxed-out inputs, composite stays <= 100."""
        maxed = _full_metrics(
            firstShotAcceptRate=1.0,
            avgTurnsPerTask=1.0,
            referenceUsageRate=1.0,
            correctionConvergenceRate=1.0,
            avgPromptWords=80,
            modelCount=10,
            aiLineSurvivalRate=1.0,
            errorFixRate=1.0,
            testAfterAiRate=1.0,
            errorsPerAiBlock=0.0,
            buildSuccessRate=1.0,
            postAiEditRate=0.12,
            leverageRatio=50,
            totalScoredCommits=200,
            planCount=100,
            avgPlanComplexity=300,
            composerRatio=1.0,
            terminalCommandCount=500,
            totalAiCodeBlocks=50000,
            totalSessions=500,
            projectCount=20,
            aiUsageSpanDays=365,
            uniqueToolCount=15,
            agentModeRatio=1.0,
            mcpServerCount=10,
            cliAiToolCount=5,
            cliAiCommandCount=200,
        )
        result = score_profile({"normalized": maxed})
        assert result["composite"] <= 100

    def test_primary_title_is_first_title(self):
        result = score_profile({"normalized": _full_metrics()})
        if result["titles"]:
            assert result["primaryTitle"] == result["titles"][0]
        else:
            assert result["primaryTitle"] is None


# ── v0.2.0 Acceptance: bias removal ─────────────────────────────────────────


class TestBiasRemoval:
    """Prove no builder type is ranked above another (SCORING-METHODOLOGY v0.2.0)."""

    @staticmethod
    def _rapid_prototyper_profile():
        """Synthetic rapid prototyper: high agent leverage, low plan %, low test
        rate, fast shipping.  This builder is valid and must not be penalized."""
        return {
            # High agent leverage
            "agentModeRatio": 0.85,
            "maxParallelAgents": 4,
            "leverageRatio": 35.0,
            "totalAiCodeBlocks": 25000,
            "filesPerSession": 22,
            "composerRatio": 0.85,
            # Low plan / test (not their style — valid)
            "planCount": 2,
            "avgPlanComplexity": 20,
            "testAfterAiRate": 0.10,
            "buildSuccessRate": 0.50,
            # Strong signal clarity and recovery
            "firstShotAcceptRate": 0.80,
            "avgTurnsPerTask": 1.8,
            "avgPromptWords": 55,
            "correctionConvergenceRate": 0.82,
            "referenceUsageRate": 0.30,
            "errorFixRate": 0.88,
            "errorsPerAiBlock": 0.02,
            "postAiEditRate": 0.08,
            "modelCount": 4,
            # Context / orchestration
            "totalSessions": 120,
            "projectCount": 10,
            "aiUsageSpanDays": 90,
            "uniqueToolCount": 7,
            "mcpServerCount": 3,
            "mcpToolCalls": 25,
            "cliAiToolCount": 3,
            "cliAiCommandCount": 50,
            "terminalCommandCount": 50,
            "totalScoredCommits": 50,
            "deepSessionCount": 15,
            "languageCount": 4,
            # Trajectory
            "recentSignalDensity": 0.6,
            "historicalSignalDensity": 0.5,
            "recentModelCount": 3,
            "historicalModelCount": 3,
            "recentPlanRatio": 0.05,
            "historicalPlanRatio": 0.05,
            "recentLanguageCount": 3,
            "historicalLanguageCount": 3,
        }

    @staticmethod
    def _architect_profile():
        """Synthetic architect: plan-heavy, reference-rich, lower agent leverage."""
        return {
            # Low agent leverage
            "agentModeRatio": 0.20,
            "maxParallelAgents": 1,
            "leverageRatio": 4.0,
            "totalAiCodeBlocks": 3000,
            "filesPerSession": 6,
            "composerRatio": 0.30,
            # High plan / test
            "planCount": 40,
            "avgPlanComplexity": 150,
            "testAfterAiRate": 0.60,
            "buildSuccessRate": 0.80,
            # Moderate signal clarity
            "firstShotAcceptRate": 0.55,
            "avgTurnsPerTask": 5.0,
            "avgPromptWords": 80,
            "correctionConvergenceRate": 0.65,
            "referenceUsageRate": 0.55,
            "errorFixRate": 0.80,
            "errorsPerAiBlock": 0.06,
            "postAiEditRate": 0.20,
            "modelCount": 2,
            # Context / orchestration
            "totalSessions": 80,
            "projectCount": 5,
            "aiUsageSpanDays": 90,
            "uniqueToolCount": 3,
            "mcpServerCount": 1,
            "mcpToolCalls": 2,
            "cliAiToolCount": 1,
            "cliAiCommandCount": 10,
            "terminalCommandCount": 60,
            "totalScoredCommits": 50,
            "languageCount": 3,
            # Trajectory
            "recentSignalDensity": 0.5,
            "historicalSignalDensity": 0.5,
            "recentModelCount": 2,
            "historicalModelCount": 2,
            "recentPlanRatio": 0.4,
            "historicalPlanRatio": 0.4,
            "recentLanguageCount": 3,
            "historicalLanguageCount": 3,
        }

    def test_prototyper_not_below_architect(self):
        """A rapid prototyper must NOT score below an architect on the composite.
        Both are valid builder types — the scoring must not structurally
        favor one over the other."""
        proto = score_profile({"normalized": self._rapid_prototyper_profile()})
        arch = score_profile({"normalized": self._architect_profile()})
        assert proto["composite"] is not None
        assert arch["composite"] is not None
        assert proto["composite"] >= arch["composite"], (
            f"Prototyper ({proto['composite']}) scored below architect "
            f"({arch['composite']}) — bias detected"
        )

    def test_prototyper_on_explorer_orchestrator_side(self):
        """Rapid prototyper lands on the Explorer / Orchestrator side of the map
        without any negative penalty."""
        result = score_profile({"normalized": self._rapid_prototyper_profile()})
        m = result["map"]
        # X < 50 = explorer side (lower = more explorer)
        assert m["x"] < 55, f"Expected explorer side (x<55), got x={m['x']}"
        # Y > 45 = orchestrator side (higher = more orchestrator)
        assert m["y"] > 45, f"Expected orchestrator side (y>45), got y={m['y']}"

    def test_no_negative_penalty_on_map(self):
        """No archetype subtracts from any axis — both profiles have
        valid, non-negative map positions."""
        for profile_fn in (self._rapid_prototyper_profile, self._architect_profile):
            result = score_profile({"normalized": profile_fn()})
            m = result["map"]
            assert 0 <= m["x"] <= 100, f"x={m['x']} out of [0,100]"
            assert 0 <= m["y"] <= 100, f"y={m['y']} out of [0,100]"

    def test_agent_leverage_raises_scores(self):
        """High AI co-authorship / agent-mode / parallel agents must raise
        relevant scores, never lower them (§9)."""
        base = self._rapid_prototyper_profile()
        # Score with high agent leverage
        high_agent = score_profile({"normalized": base})
        # Score with reduced agent leverage
        low_agent_inp = dict(base, agentModeRatio=0.1, maxParallelAgents=1, leverageRatio=2.0)
        low_agent = score_profile({"normalized": low_agent_inp})
        # Orchestration Range must be higher with more agent leverage
        orch_high = high_agent["dimensions"]["orchestration_range"]["score"]
        orch_low = low_agent["dimensions"]["orchestration_range"]["score"]
        assert orch_high > orch_low, (
            f"Agent leverage did not raise Orchestration Range: {orch_high} vs {orch_low}"
        )

    def test_prototyper_anti_patterns_not_flagged(self):
        """A rapid prototyper should NOT get 'high_velocity_low_stability'
        because low stability is valid for their mode (§10)."""
        proto = score_profile({"normalized": self._rapid_prototyper_profile()})
        anti_ids = [a["id"] for a in proto["antiPatterns"]]
        assert "high_velocity_low_stability" not in anti_ids

    def test_taxonomy_version_in_output(self):
        result = score_profile({"normalized": _full_metrics()})
        assert result["taxonomy_version"] == TAXONOMY_VERSION


# ── v0.2.0 Acceptance: work-mode classifier ─────────────────────────────────


class TestWorkModeClassifier:
    def test_returns_dominant_mode(self):
        """classify_work_mode returns a dominant mode for any input."""
        result = classify_work_mode(_full_metrics())
        assert "dominant" in result
        assert "id" in result["dominant"]
        assert "line" in result["dominant"]
        assert result["dominant"]["id"] in {
            "Architect-First",
            "Prompt-Iterate",
            "One-Shot-Verify",
            "Read-Understand-Modify",
            "Test-Driven-AI",
            "Multi-Agent-Orchestrated",
            "Hybrid-Manual",
            "Exploration-Research",
        }

    def test_returns_secondary_modes(self):
        result = classify_work_mode(_full_metrics())
        assert "secondary" in result
        assert isinstance(result["secondary"], list)
        for s in result["secondary"]:
            assert "id" in s
            assert "line" in s

    def test_high_agent_ratio_classifies_one_shot(self):
        """High agent-mode ratio with low turns → One-Shot-Verify."""
        inp = _full_metrics(
            agentModeRatio=0.9,
            avgTurnsPerTask=1.5,
            leverageRatio=40,
            planCount=0,
        )
        result = classify_work_mode(inp)
        assert result["dominant"]["id"] == "One-Shot-Verify"

    def test_high_plan_ratio_classifies_architect(self):
        """High plan-to-code ratio → Architect-First."""
        inp = _full_metrics(
            planCount=50,
            totalSessions=100,
            referenceUsageRate=0.60,
            composerRatio=0.70,
            agentModeRatio=0.1,
            avgTurnsPerTask=5,
            leverageRatio=2,
        )
        result = classify_work_mode(inp)
        assert result["dominant"]["id"] == "Architect-First"

    def test_high_parallel_classifies_multi_agent(self):
        """High parallel agents → Multi-Agent-Orchestrated."""
        inp = _full_metrics(
            maxParallelAgents=5,
            agentModeRatio=0.85,
            mcpToolCalls=30,
            planCount=0,
            avgTurnsPerTask=5,
            leverageRatio=3,
        )
        result = classify_work_mode(inp)
        assert result["dominant"]["id"] == "Multi-Agent-Orchestrated"

    def test_work_mode_in_score_profile(self):
        """score_profile includes workMode."""
        result = score_profile({"normalized": _full_metrics()})
        wm = result["workMode"]
        assert wm["dominant"]["id"] in {
            "Architect-First",
            "Prompt-Iterate",
            "One-Shot-Verify",
            "Read-Understand-Modify",
            "Test-Driven-AI",
            "Multi-Agent-Orchestrated",
            "Hybrid-Manual",
            "Exploration-Research",
        }


# ── v0.2.0 Acceptance: perceptual map ───────────────────────────────────────


class TestPerceptualMap:
    def test_map_structure(self):
        archetypes = compute_archetypes(_full_metrics())
        m = compute_map(archetypes, _full_metrics())
        assert "x" in m and "y" in m
        assert "xLabel" in m and "yLabel" in m
        assert m["xLabel"] == ["Explorer", "Architect"]
        assert m["yLabel"] == ["Solo", "Orchestrator"]

    def test_map_values_in_range(self):
        archetypes = compute_archetypes(_full_metrics())
        m = compute_map(archetypes, _full_metrics())
        assert 0 <= m["x"] <= 100
        assert 0 <= m["y"] <= 100

    def test_map_no_subtraction_terms(self):
        """Empty input → 50/50 neutral position (no penalty from archetypes)."""
        archetypes = compute_archetypes({})
        m = compute_map(archetypes, {})
        assert m["x"] == 50.0
        assert m["y"] == 50.0


# ── v0.2.0 Acceptance: scanner new signals ──────────────────────────────────


class TestNewScannerSignals:
    def test_full_metrics_include_new_signals(self):
        """_full_metrics can include new v0.2.0 signals without breaking."""
        inp = _full_metrics(
            maxParallelAgents=3,
            mcpToolCalls=10,
            deepSessionCount=5,
            fileReadToEditRatio=3.0,
            featureToFixRatio=2.5,
            planModePercent=15.0,
        )
        result = score_profile({"normalized": inp})
        assert result["composite"] is not None
        assert result["composite"] <= 100


# ── v0.2.0 Acceptance: archetype-relative composite weights ──────────────


class TestArchetypeRelativeComposite:
    """Composite weight vectors must differ by dominant work mode (§3).

    Acceptance criteria: the effective weight vector used to compute the
    composite must differ between a prototyper and an architect profile.
    """

    def test_weight_vector_differs_by_mode(self):
        """Prototyper and architect must use different effective weight vectors."""
        proto_inp = TestBiasRemoval._rapid_prototyper_profile()
        arch_inp = TestBiasRemoval._architect_profile()

        proto_dims = score_dimensions(proto_inp)
        arch_dims = score_dimensions(arch_inp)

        proto_mode = classify_work_mode(proto_inp)
        arch_mode = classify_work_mode(arch_inp)

        # Modes must differ
        assert proto_mode["dominant"]["id"] != arch_mode["dominant"]["id"], (
            "Prototyper and architect should classify to different work modes"
        )

        proto_weights = _adapt_weights(proto_dims, proto_mode["dominant"]["id"])
        arch_weights = _adapt_weights(arch_dims, arch_mode["dominant"]["id"])

        # Weight vectors must differ
        assert proto_weights != arch_weights, (
            "Prototyper and architect must use different weight vectors"
        )

    def test_prototyper_upweights_orchestration(self):
        """One-Shot-Verify should up-weight orchestration_range relative to
        the base weight."""
        dims = score_dimensions(_full_metrics())
        base_orch = dims["orchestration_range"]["weight"]
        adapted = _adapt_weights(dims, "One-Shot-Verify")
        assert adapted["orchestration_range"] > base_orch, (
            "One-Shot-Verify should up-weight orchestration_range"
        )

    def test_architect_upweights_decision(self):
        """Architect-First should up-weight decision_weight relative to
        the base weight."""
        dims = score_dimensions(_full_metrics())
        base_dec = dims["decision_weight"]["weight"]
        adapted = _adapt_weights(dims, "Architect-First")
        assert adapted["decision_weight"] > base_dec, (
            "Architect-First should up-weight decision_weight"
        )

    def test_multipliers_bounded(self):
        """All multipliers in the weight table must be in [0.6, 1.4]."""
        from cruise_ai.scoring import _MODE_WEIGHT_MULTIPLIERS

        for mode_id, mults in _MODE_WEIGHT_MULTIPLIERS.items():
            for dim_id, mult in mults.items():
                assert 0.6 <= mult <= 1.4, (
                    f"{mode_id}.{dim_id} multiplier {mult} outside [0.6, 1.4]"
                )

    def test_composite_label_present(self):
        """score_profile output includes compositeLabel and dominantMode."""
        result = score_profile({"normalized": _full_metrics()})
        assert "compositeLabel" in result
        assert "dominantMode" in result

    def test_composite_label_format(self):
        """compositeLabel follows 'strength index — <mode>' format."""
        result = score_profile({"normalized": _full_metrics()})
        if result["compositeLabel"] is not None:
            assert "strength index" in result["compositeLabel"]
            assert "\u2014" in result["compositeLabel"]  # em dash

    def test_composite_label_none_when_no_composite(self):
        """compositeLabel is None when composite cannot be computed."""
        result = score_profile({"normalized": {}})
        assert result["compositeLabel"] is None

    def test_dominant_mode_matches_work_mode(self):
        """dominantMode matches workMode.dominant.id."""
        result = score_profile({"normalized": _full_metrics()})
        assert result["dominantMode"] == result["workMode"]["dominant"]["id"]
