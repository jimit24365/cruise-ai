"""Enforcement for the signal dependency registry — a derived field
without declared inputs is a CI failure, not a code-review hope."""

from cruise_ai.signal_registry import DERIVED, LEDGER_SUPERSEDED, SOURCES


def test_every_wrapped_stat_is_registered():
    from cruise_ai.scoring import build_wrapped_stats

    stats = build_wrapped_stats({}, {"dominant": {"id": "x", "line": ""}})
    missing = set(stats) - set(DERIVED)
    assert not missing, (
        f"wrappedStats fields without declared dependencies: {missing} — "
        "register them in signal_registry.DERIVED (inputs + rule + basis)"
    )


def test_every_profile_signal_is_registered():
    # the keys cmd_assess writes into profile["signals"]
    signal_keys = {
        "ai_code_blocks",
        "ai_lines_survived",
        "scored_commits",
        "architecture_plans",
        "models_used",
    }
    missing = signal_keys - set(DERIVED)
    assert not missing


def test_ledger_superseded_fields_are_registered_and_say_so():
    for field in LEDGER_SUPERSEDED:
        assert field in DERIVED, f"{field} superseded by ledger but unregistered"
        entry = DERIVED[field]
        joined = (entry["rule"] + " ".join(entry["inputs"])).lower()
        assert "ledger" in joined or "union" in joined, (
            f"{field}: registry entry must state its durable-supersede rule"
        )


def test_all_inputs_are_known_sources():
    for field, entry in DERIVED.items():
        unknown = set(entry["inputs"]) - SOURCES
        assert not unknown, f"{field} declares unknown inputs {unknown}"
        assert entry["rule"].strip(), f"{field} has no recompute rule"
        assert entry["basis"].strip(), f"{field} has no honest basis"


def test_estimates_declare_the_research_band():
    """Anything anchored to literature (not counted from local data)
    must say so via the research_band pseudo-source."""
    entry = DERIVED["soloEquivalentHours"]
    assert "research_band" in entry["inputs"]
    assert "estimate" in entry["rule"].lower()


# ── Staleness: commands must flag an assessment older than its inputs ────────


def test_assessment_staleness_detects_input_changes(tmp_path, monkeypatch):
    import os
    import time

    from cruise_ai.profile_data import assessment_staleness

    monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))
    data = tmp_path / "data"
    data.mkdir(parents=True)

    assert assessment_staleness() == ["no assessment yet"]

    profile = data / "profile.json"
    profile.write_text("{}")
    old = time.time() - 3600
    os.utime(profile, (old, old))

    assert assessment_staleness() == []  # nothing newer → fresh

    (data / "consent.json").write_text("{}")  # consent changed after assess
    reasons = assessment_staleness()
    assert any("consent" in r for r in reasons)

    sync = data / "sync" / "devices"
    sync.mkdir(parents=True)
    (sync / "other.json").write_text("{}")
    reasons = assessment_staleness()
    assert any("synced device" in r for r in reasons)

    # re-assess (profile newer than everything) → fresh again
    profile.write_text("{}")
    assert assessment_staleness() == []
