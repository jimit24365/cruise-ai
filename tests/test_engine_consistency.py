"""THE ENGINE invariants.

Two rules this file makes structural:

1. **One fact, one value.** The same underlying fact must never show two
   different numbers across profile sections (the streak bug: the card
   said 4 while activity said 10). Cross-surface invariants below run
   over a full real pipeline pass (cmd_assess on a fixture home).
2. **Engine change ⇒ full recompute.** A schema/methodology bump
   invalidates the scan cache, the assessment records which engine
   produced it, staleness reports an engine mismatch, and the docs
   header cannot drift from the code constant.
"""

import json

import pytest

from nextmillionai.schema import METHODOLOGY_VERSION, SCHEMA_VERSION

# ── Engine-version plumbing ──────────────────────────────────────────────────


def test_methodology_constant_matches_doc_header():
    from nextmillionai.paths import DOCS_DIR

    head = (DOCS_DIR / "SCORING-METHODOLOGY.md").read_text()[:2000]
    assert f"`{METHODOLOGY_VERSION}`" in head, (
        "schema.METHODOLOGY_VERSION and the SCORING-METHODOLOGY.md header "
        "have drifted — bump both in the same commit"
    )


def test_stale_engine_invalidates_scan_cache():
    from nextmillionai.build_profile import _scan_cache_valid

    fresh = {"engine": {"schema": SCHEMA_VERSION, "methodology": METHODOLOGY_VERSION}}
    assert _scan_cache_valid(fresh, code_scan=False) is True

    old_engine = {"engine": {"schema": SCHEMA_VERSION, "methodology": "0.0.1"}}
    assert _scan_cache_valid(old_engine, code_scan=False) is False

    unstamped = {"schema_version": SCHEMA_VERSION}  # pre-stamp cache
    assert _scan_cache_valid(unstamped, code_scan=False) is False

    no_code_intel = dict(fresh)
    assert _scan_cache_valid(no_code_intel, code_scan=True) is False


def test_staleness_flags_engine_mismatch(tmp_path, monkeypatch):
    from nextmillionai.profile_data import assessment_staleness

    monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path))
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "profile.json").write_text(json.dumps({"assessment": {"methodology_version": "0.0.1"}}))
    reasons = assessment_staleness()
    assert any("engine 0.0.1" in r for r in reasons)


# ── One fact, one value: full-pipeline cross-surface invariants ──────────────


@pytest.fixture()
def assessed_profile(tmp_path, monkeypatch):
    """Run the REAL cmd_assess over a synthetic home and return the JSON."""
    import nextmillionai.scanner as scanner_mod
    from nextmillionai.build_profile import cmd_assess
    from nextmillionai.consent import save_consent

    monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path / "nma"))

    # One Claude project with two dated sessions (one >2h marathon with
    # an idle gap, one short) + a subagent run
    proj = tmp_path / "claude" / "-Users-dev-app"
    sub = proj / "s1" / "subagents"
    sub.mkdir(parents=True)

    def _line(kind, ts, text="hi"):
        return json.dumps(
            {
                "type": kind,
                "timestamp": ts,
                "message": {
                    "content": text if kind == "user" else [{"type": "text", "text": text}]
                },
                "cwd": "/Users/dev/app",
            }
        )

    s1 = [
        _line("user", "2026-06-01T09:00:00Z", "build the thing"),
        _line("assistant", "2026-06-01T09:20:00Z"),
        _line("user", "2026-06-01T09:40:00Z", "continue"),
        _line("assistant", "2026-06-01T11:30:00Z"),  # >30min gap → idle split
        _line("user", "2026-06-01T11:40:00Z", "finish"),
        _line("assistant", "2026-06-01T13:50:00Z"),  # another long stretch
    ]
    (proj / "s1.jsonl").write_text("\n".join(s1))
    (sub / "agent-a1.jsonl").write_text(
        "\n".join(
            [
                _line("user", "2026-06-01T09:21:00Z", "go"),
                _line("assistant", "2026-06-01T09:51:00Z"),
            ]
        )
    )
    s2 = [
        _line("user", "2026-06-02T10:00:00Z", "quick fix"),
        _line("assistant", "2026-06-02T10:10:00Z"),
    ]
    (proj / "s2.jsonl").write_text("\n".join(s2))

    monkeypatch.setattr(scanner_mod, "CLAUDE_PROJECTS_DIR", tmp_path / "claude")
    monkeypatch.setattr(scanner_mod, "CURSOR_DIR", tmp_path / "no-cursor")
    monkeypatch.setattr(scanner_mod, "CODEX_SESSIONS_DIR", tmp_path / "no-codex")
    save_consent(
        {
            "claude_code": True,
            "cursor": False,
            "codex": False,
            "git": False,
            "other_tools": False,
            "local_models": False,
            "claude_desktop": False,
        }
    )

    class Args:
        yes = True
        rescan = True
        project = None
        code = False

    cmd_assess(Args())
    from nextmillionai.paths import profile_path

    return json.loads(profile_path().read_text())


def test_one_fact_one_value(assessed_profile):
    p = assessed_profile
    ws = p["wrappedStats"]
    act = p["activity"]
    am = p["assessment"]

    # The streak: card and activity block must agree (the original bug)
    assert ws["longestStreakDays"] == act["streak"]

    # Session counts: assessment header, activity block — one number
    assert am["sessions"] == act["totalSessions"]

    # Dispatch evidence: wrapped card and harness must agree
    assert ws["subagentDispatches"] == p["harness"]["subagentDispatches"]

    # Tiers nest: marathons ⊆ deep ⊆ total
    assert ws["marathonSessionCount"] <= ws["deepSessionCount"] <= act["totalSessions"]

    # Longest session can never be shorter than what makes a marathon
    if ws["marathonSessionCount"]:
        assert ws["longestSessionMinutes"] >= 120

    # The calendar and the date range tell the same story
    days = [d["date"] for d in p["activityByDay"] if d.get("date")]
    assert days == sorted(days)
    assert am["dateRange"].startswith(days[0]) and am["dateRange"].endswith(days[-1])

    # Engine stamp present
    assert am["methodology_version"] == METHODOLOGY_VERSION

    # Hours: the gap-based estimator actually excluded the idle stretches
    # (s1 active ≈ 20+130min-split... measured well below its 4.8h span)
    assert 0 < ws["totalActiveHours"] < 4.0


def test_assess_is_deterministic(assessed_profile, tmp_path):
    """Same inputs, same engine → byte-identical derived output."""
    from nextmillionai.scoring import score_profile

    scan = json.loads((tmp_path / "nma" / "data" / "scan_results.json").read_text())
    a = score_profile(scan)
    b = score_profile(scan)
    # scoredAt is run metadata, not a derived value
    a.pop("scoredAt", None)
    b.pop("scoredAt", None)
    assert a == b


def test_formula_fingerprint_pins_scoring_to_its_doc():
    """Semantic hash (AST — comments/formatting don't count) of every
    score_*/compute_* function and UPPERCASE constant in scoring.py must
    match the fingerprint recorded in SCORING-METHODOLOGY.md. Scoring
    semantics can then never change as a side effect: any drift goes red
    until the methodology doc is deliberately revisited (and, for real
    formula changes, the methodology version bumped with sign-off —
    docs/HARDLINES.md). Refresh: scripts/formula_fingerprint.py --update"""
    import importlib.util
    from pathlib import Path

    from nextmillionai.paths import DOCS_DIR

    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "formula_fingerprint", root / "scripts" / "formula_fingerprint.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    computed = mod.compute_fingerprint()
    doc = (DOCS_DIR / "SCORING-METHODOLOGY.md").read_text()[:2000]
    m = mod.LINE_RE.search(doc)
    assert m, "SCORING-METHODOLOGY.md header lost its 'Formula fingerprint:' line"
    assert m.group(1) == computed, (
        f"scoring.py semantics changed (fingerprint {computed} != doc {m.group(1)}). "
        "If this is a signed-off methodology change: bump METHODOLOGY_VERSION, "
        "update SCORING-METHODOLOGY.md, and run "
        "`python3 scripts/formula_fingerprint.py --update`. "
        "If not — revert; formulas never move as a side effect."
    )
