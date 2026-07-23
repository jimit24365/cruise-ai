"""The documented tool coverage must match what the engine actually reads.

The engine reads 18 sources (4 first-class + 10 wider-field + 3 local runtimes +
Claude Desktop + custom adapters), but the methodology copy used to say only
"Claude Code, Cursor, Codex". These tests pin the canonical TOOL_COVERAGE in
methodology_spec.py to the adapter registry: every session adapter the registry
instantiates must be documented, every declared tier must match the adapter's
own fidelity, and git + the local runtimes must be present. So the methodology
can never silently under-state — or mis-tier — what is read.
"""

from nextmillionai.adapters._registry import get_git_adapter, get_session_adapters
from nextmillionai.methodology_spec import TOOL_COVERAGE, coverage_ids


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
    from nextmillionai.adapters.local_tools import get_local_tool_adapters

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


def test_raw_declared_fidelity_matches_documented_tier(tmp_path):
    """First-class adapters that self-declare fidelity in raw_data must
    match their documented TOOL_COVERAGE tier — the wider-field check
    above never covered first-class adapters, so a docs/code tier drift
    there was silent (provenance would even downgrade an undeclared one
    to 'counts' while the docs said 'deep')."""
    import json

    from nextmillionai.adapters.kiro import KiroAdapter

    declared = {t["id"]: t["tier"] for grp in TOOL_COVERAGE.values() for t in grp}

    # Kiro: scan a minimal synthetic store and compare the raw declaration.
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
    adapter = KiroAdapter(sessions_dir=kiro_dir, ide_dirs=[])
    adapter.scan()
    raw = adapter.raw_data()
    assert raw is not None and raw.get("fidelity"), (
        "kiro raw_data must self-declare fidelity — provenance downgrades an "
        "undeclared payload to 'counts'"
    )
    assert raw["fidelity"] == declared["kiro"], (
        f"kiro: raw fidelity '{raw['fidelity']}' != TOOL_COVERAGE tier "
        f"'{declared['kiro']}' — fix the drift."
    )
