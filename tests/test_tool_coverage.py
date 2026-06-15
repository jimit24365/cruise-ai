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
