"""Methodology change proposals stay valid and the index stays fresh.

The proposal workflow (``docs/proposals/`` + ``scripts/proposals.py``) is
how a versioned-contract change is made explicit and reviewed before the
engine moves. These tests give the workflow teeth: a malformed proposal,
a stale version base, or a stale index fails CI — same as any contract.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("_proposals", ROOT / "scripts" / "proposals.py")
proposals = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(proposals)


def test_all_proposals_are_valid():
    _, errs = proposals.validate_all()
    assert not errs, "invalid proposals:\n  - " + "\n  - ".join(errs)


def test_proposal_ids_unique_and_match_filename():
    seen = set()
    for rec in proposals.discover():
        fid = rec["meta"]["id"]
        assert fid not in seen, f"duplicate proposal id {fid}"
        seen.add(fid)
        assert rec["path"].name.startswith(fid + "-")


def test_statuses_are_legal():
    for rec in proposals.discover():
        assert rec["meta"]["status"] in proposals.STATUSES


def test_index_is_up_to_date():
    """Mirror the DERIVATIONS.md @generated guard: the checked-in index
    must equal a fresh render, so the directory can't drift from its TOC."""
    assert proposals.INDEX.exists(), "run `python3 scripts/proposals.py render`"
    want = proposals.render_index().rstrip() + "\n"
    assert proposals.INDEX.read_text() == want, (
        "docs/proposals/README.md is stale — run `python3 scripts/proposals.py render` and commit"
    )


def test_open_proposals_declare_a_live_version_base():
    """An open proposal's declared base version must match the live engine
    constant — the single-source-of-truth check that catches a proposal
    drafted against an old methodology version."""
    live = proposals.live_versions()
    for rec in proposals.discover():
        if rec["meta"]["status"] not in proposals.OPEN_STATUSES:
            continue
        for key, val in (rec["meta"].get("target_versions") or {}).items():
            if not val:
                continue
            base = val.split("->")[0].strip()
            assert base == live[key], f"{rec['path'].name}: {key} base {base} != live {live[key]}"
