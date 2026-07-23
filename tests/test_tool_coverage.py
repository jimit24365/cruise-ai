"""The documented tool coverage must match what the engine actually reads.

The engine reads 18 sources (4 first-class + 10 wider-field + 3 local runtimes +
Claude Desktop + custom adapters), but the methodology copy used to say only
"Claude Code, Cursor, Codex". These tests pin the canonical TOOL_COVERAGE in
methodology_spec.py to the adapter registry: every session adapter the registry
instantiates must be documented, every declared tier must match the adapter's
own fidelity, and git + the local runtimes must be present. So the methodology
can never silently under-state — or mis-tier — what is read.
"""

from cruise_ai.adapters._registry import get_git_adapter, get_session_adapters
from cruise_ai.methodology_spec import TOOL_COVERAGE, coverage_ids


def test_every_session_adapter_is_documented():
    ids = coverage_ids()
    for a in get_session_adapters():
        assert a.name in ids, (
            f"adapter '{a.name}' is read by the engine but missing from "
            "methodology_spec.TOOL_COVERAGE — document it (the methodology would "
            "otherwise under-state what we read)."
        )


def test_git_and_local_runtimes_are_documented():
    ids = coverage_ids()
    assert get_git_adapter().name in ids
    for runtime in ("ollama", "lmstudio", "llamacpp"):
        assert runtime in ids, f"local runtime {runtime} missing from TOOL_COVERAGE"


def test_declared_tier_matches_adapter_fidelity():
    from cruise_ai.adapters.local_tools import get_local_tool_adapters

    declared = {t["id"]: t["tier"] for grp in TOOL_COVERAGE.values() for t in grp}
    for a in get_local_tool_adapters():
        if a.name in declared and getattr(a, "fidelity", None):
            assert declared[a.name] == a.fidelity, (
                f"{a.name}: TOOL_COVERAGE tier '{declared[a.name]}' != adapter "
                f"fidelity '{a.fidelity}' — fix the drift."
            )


def test_every_entry_is_well_formed():
    for tier_group, entries in TOOL_COVERAGE.items():
        for t in entries:
            assert t["id"] and t["label"] and t["reads"], f"{tier_group} entry incomplete: {t}"
            assert t["tier"] in ("deep", "counts", "presence"), f"bad tier: {t}"


def _seeded_kiro_adapter(tmp_path):
    """A KiroAdapter over a minimal synthetic store (never a real ~/.kiro)."""
    import json

    from cruise_ai.adapters.kiro import KiroAdapter

    kiro_dir = tmp_path / "cli"
    kiro_dir.mkdir()
    sid = "fidelity-test-0000-0000-000000000001"
    (kiro_dir / f"{sid}.json").write_text(
        json.dumps(
            {
                "session_id": sid,
                "cwd": "/tmp/p",
                "created_at": "2026-07-01T10:00:00Z",
                "updated_at": "2026-07-01T10:05:00Z",
                "session_state": {},
            }
        )
    )
    (kiro_dir / f"{sid}.jsonl").write_text(
        json.dumps(
            {
                "version": "v1",
                "kind": "Prompt",
                "data": {"message_id": "m", "content": [{"kind": "text", "data": "hi"}]},
            }
        )
    )
    return KiroAdapter(sessions_dir=kiro_dir, ide_dirs=[])


# First-class adapters whose raw_data self-declares fidelity, with a
# factory building each over a synthetic store. When a new first-class
# adapter self-declares fidelity, ADD IT HERE — otherwise its docs/code
# tier drift is silent (the wider-field check above never covers
# first-class adapters, and provenance downgrades an undeclared payload
# to 'counts' while the docs may say 'deep').
_SELF_DECLARING_FIRST_CLASS = {
    "kiro": _seeded_kiro_adapter,
}


def test_raw_declared_fidelity_matches_documented_tier(tmp_path):
    declared = {t["id"]: t["tier"] for grp in TOOL_COVERAGE.values() for t in grp}
    for name, factory in _SELF_DECLARING_FIRST_CLASS.items():
        adapter = factory(tmp_path)
        adapter.scan()
        raw = adapter.raw_data()
        assert raw is not None and raw.get("fidelity"), (
            f"{name}: raw_data must self-declare fidelity — provenance "
            "downgrades an undeclared payload to 'counts'"
        )
        assert raw["fidelity"] == declared[name], (
            f"{name}: raw fidelity '{raw['fidelity']}' != TOOL_COVERAGE tier "
            f"'{declared[name]}' — fix the drift."
        )


def test_first_class_tools_named_in_served_scope():
    """The served /methodology scope copy must name every first-class
    session tool — a stale 'Claude Code, Cursor, and Codex' string there
    contradicts the coverage table two sections away (exactly what
    happened when Kiro landed)."""
    from cruise_ai.methodology_spec import SCOPE

    first_class = [t["label"] for t in TOOL_COVERAGE.get("firstClass", [])]
    body = SCOPE["body"]
    for label in first_class:
        if label.lower() == "git":
            continue  # git is covered by "your git history" phrasing
        assert label in body, (
            f"first-class tool '{label}' missing from the served scope copy "
            f"(methodology_spec.SCOPE body) — the /methodology page would "
            f"under-state coverage."
        )
