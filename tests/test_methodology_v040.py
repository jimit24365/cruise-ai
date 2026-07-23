"""Methodology 0.4.0 — the deliberate version bump tests.

Each new signal must move ONLY its intended dimension; profiles without
the new signals must be bit-identical to before; insufficient stays
insufficient. No score moves without a counted signal behind it.
"""

from cruise_ai.schema import SCHEMA_VERSION
from cruise_ai.scoring import score_dimensions, score_profile

BASE = {
    "totalSessions": 40,
    "totalScoredCommits": 30,
    "projectCount": 6,
    "aiUsageSpanDays": 120,
    "modelCount": 2,
    "mcpServerCount": 2,
    "uniqueToolCount": 3,
    "maxParallelAgents": 1,
    "agentModeRatio": 0.4,
    "referenceUsageRate": 0.3,
    "firstShotAcceptRate": 0.5,
    "deepSessionCount": 8,
    "avgPromptWords": 30,
}

DIMS = (
    "signal_clarity",
    "build_stability",
    "decision_weight",
    "recovery_velocity",
    "context_command",
    "orchestration_range",
)


def _scores(inp):
    return {k: v.get("score") for k, v in score_dimensions(inp).items()}


def test_version_bumped():
    assert SCHEMA_VERSION == "1.1"
    profile = score_profile({"normalized": dict(BASE)})
    assert profile["schema_version"] == "1.1"


def test_dispatches_move_only_orchestration_range():
    before = _scores(dict(BASE))
    after = _scores({**BASE, "subagentDispatches": 48, "sessionsWithSubagents": 9})
    assert after["orchestration_range"] > before["orchestration_range"]
    for dim in DIMS:
        if dim != "orchestration_range":
            assert after[dim] == before[dim], f"{dim} moved without a counted signal"


def test_zero_dispatches_change_nothing():
    """Absence of the new signal must not dilute anyone's score."""
    before = _scores(dict(BASE))
    after = _scores({**BASE, "subagentDispatches": 0, "sessionsWithSubagents": 0})
    assert after == before


def test_surface_breadth_moves_only_context_command():
    before = _scores(dict(BASE))
    after = _scores({**BASE, "activeSurfaceCount": 4})
    assert after["context_command"] > before["context_command"]
    for dim in DIMS:
        if dim != "context_command":
            assert after[dim] == before[dim], f"{dim} moved without a counted signal"


def test_single_surface_changes_nothing():
    """One surface (or merely-detected tools) is not breadth — detecting
    more tools must never raise a score by itself."""
    before = _scores(dict(BASE))
    after = _scores({**BASE, "activeSurfaceCount": 1})
    assert after == before


def test_dispatch_evidence_lands_in_orchestration():
    dims = score_dimensions({**BASE, "subagentDispatches": 48, "sessionsWithSubagents": 9})
    ev = " ".join(dims["orchestration_range"]["evidence"])
    assert "48 subagent dispatches" in ev


def test_insufficient_stays_insufficient():
    """A profile with no measurable inputs keeps None scores — the new
    sub-signals never fabricate a measurement."""
    dims = score_dimensions({})
    for key in ("context_command", "orchestration_range"):
        assert dims[key]["score"] is None, f"{key} fabricated a score from nothing"


def test_dispatches_alone_do_not_fabricate_context():
    """Dispatches with no context inputs: orchestration becomes
    measurable, context command stays insufficient."""
    dims = score_dimensions({"subagentDispatches": 20, "sessionsWithSubagents": 5})
    assert dims["orchestration_range"]["score"] is not None
    assert dims["context_command"]["score"] is None
