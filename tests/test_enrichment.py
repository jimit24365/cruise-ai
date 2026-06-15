"""Tests for enrichment validation, ingest, and revoke.

The enrichment contract (ENRICHMENT-PROMPT.md): six narrative blocks +
positioningLine, derived-only, no raw code, no ranking language, no
off-schema keys. Ingest is idempotent, timestamped, and revocable —
and never touches scores.
"""

import json

import pytest

from nextmillionai.enrichment import (
    build_heuristic_enrichment,
    ingest_enrichment,
    parse_submission,
    revoke_enrichment,
    validate_enrichment,
)


def make_valid_result() -> dict:
    return {
        "narrative": "Strongest when orchestrating agents across repos.",
        "positioningLine": "An ai_systems builder operating at the harnessing level.",
        "whatYouBuilt": ["Built a local-first profile builder across 7 projects."],
        "decisionPatterns": {
            "style": "Constrains scope early, verifies after delegation.",
            "stats": {"detected": 4, "byDomain": {"architecture": 2}, "highValue": 1},
            "named": [{"name": "Close the Loop", "evidence": "verify step in session 3"}],
        },
        "strengths": [{"claim": "Multi-tool range", "evidence": "3 tools, 12 MCP calls"}],
        "growthAreas": [
            {
                "observed": "Asked for subagents but none dispatched.",
                "nextSignal": "One dispatched subagent run.",
            }
        ],
        "howYouUseAI": {
            "persona": "Fleet Commander",
            "line": "Runs the fleet.",
            "evidencePoints": 2,
        },
    }


class TestValidateEnrichment:
    def test_valid_result_passes(self):
        valid, err = validate_enrichment(make_valid_result())
        assert valid, err

    def test_missing_block_rejected(self):
        result = make_valid_result()
        del result["strengths"]
        valid, err = validate_enrichment(result)
        assert not valid
        assert "strengths" in err

    def test_missing_positioning_line_rejected(self):
        result = make_valid_result()
        del result["positioningLine"]
        valid, _ = validate_enrichment(result)
        assert not valid

    def test_off_schema_key_rejected(self):
        result = make_valid_result()
        result["overallRank"] = 3
        valid, err = validate_enrichment(result)
        assert not valid
        assert "Off-schema" in err

    def test_ingest_metadata_keys_tolerated(self):
        result = make_valid_result()
        result["generatedAt"] = "2026-06-11T00:00:00Z"
        result["source"] = "agent"
        valid, err = validate_enrichment(result)
        assert valid, err

    def test_code_fence_in_value_rejected(self):
        result = make_valid_result()
        result["whatYouBuilt"] = ["Here is the fix:\n```python\nx = 1\n```"]
        valid, err = validate_enrichment(result)
        assert not valid
        assert "raw code" in err

    def test_verbatim_code_rejected(self):
        result = make_valid_result()
        result["narrative"] = "def score_profile(data): return 100"
        valid, _ = validate_enrichment(result)
        assert not valid

    @pytest.mark.parametrize(
        "phrase",
        [
            "You are in the top 5% of builders.",
            "Ranks at the 90th percentile.",
            "Better than most engineers.",
            "Consistently outperforms the cohort.",
        ],
    )
    def test_ranking_language_rejected(self, phrase):
        result = make_valid_result()
        result["narrative"] = phrase
        valid, err = validate_enrichment(result)
        assert not valid
        assert "ranking" in err.lower() or "raw code" in err

    def test_wrong_nested_shapes_rejected(self):
        result = make_valid_result()
        result["decisionPatterns"]["stats"] = {"detected": "four"}
        valid, _ = validate_enrichment(result)
        assert not valid

    def test_empty_arrays_are_valid(self):
        # NO FABRICATION rule: empty arrays/zeros are honest and valid.
        result = make_valid_result()
        result["whatYouBuilt"] = []
        result["strengths"] = []
        result["growthAreas"] = []
        result["decisionPatterns"]["named"] = []
        valid, err = validate_enrichment(result)
        assert valid, err


class TestParseSubmission:
    def test_plain_json(self):
        result, err = parse_submission(json.dumps(make_valid_result()))
        assert result is not None, err

    def test_outer_fence_wrapper_stripped(self):
        wrapped = "```json\n" + json.dumps(make_valid_result()) + "\n```"
        result, err = parse_submission(wrapped)
        assert result is not None, err

    def test_invalid_json_rejected(self):
        result, err = parse_submission("not json at all")
        assert result is None
        assert "invalid JSON" in err

    def test_non_object_rejected(self):
        result, err = parse_submission("[1, 2, 3]")
        assert result is None


class TestIngestAndRevoke:
    def _write_profile(self, tmp_path):
        profile = {
            "composite": 72,
            "dimensions": {},
            "workMode": {"dominant": {"id": "One-Shot-Verify", "line": ""}},
            "archetypes": [],
            "positioning": {},
            "wrappedStats": {},
            "growthEdge": {},
        }
        p = tmp_path / "profile.json"
        p.write_text(json.dumps(profile))
        return p

    def test_ingest_stamps_metadata_and_keeps_scores(self, tmp_path):
        p = self._write_profile(tmp_path)
        ok, msg = ingest_enrichment(make_valid_result(), p)
        assert ok, msg
        saved = json.loads(p.read_text())
        assert saved["composite"] == 72  # scores never change
        assert saved["enrichment"]["source"] == "agent"
        assert saved["enrichment"]["generatedAt"]

    def test_ingest_is_idempotent(self, tmp_path):
        p = self._write_profile(tmp_path)
        ingest_enrichment(make_valid_result(), p)
        second = make_valid_result()
        second["narrative"] = "A different narrative."
        ok, _ = ingest_enrichment(second, p)
        assert ok
        saved = json.loads(p.read_text())
        assert saved["enrichment"]["narrative"] == "A different narrative."

    def test_rejected_result_not_written(self, tmp_path):
        p = self._write_profile(tmp_path)
        bad = make_valid_result()
        bad["extraField"] = "nope"
        ok, _ = ingest_enrichment(bad, p)
        assert not ok
        assert "enrichment" not in json.loads(p.read_text())

    def test_revoke_restores_heuristic(self, tmp_path):
        p = self._write_profile(tmp_path)
        ingest_enrichment(make_valid_result(), p)
        ok, msg = revoke_enrichment(p)
        assert ok, msg
        saved = json.loads(p.read_text())
        assert saved["enrichment"]["source"] == "heuristic"

    def test_secret_stripped_on_ingest(self, tmp_path):
        p = self._write_profile(tmp_path)
        result = make_valid_result()
        result["narrative"] = "Used key sk-abcdefghijklmnopqrstuvwxyz123456 to call the API."
        ok, msg = ingest_enrichment(result, p)
        assert ok, msg
        saved = json.loads(p.read_text())
        assert "sk-abcdefghijklmnop" not in json.dumps(saved)
        assert "[REDACTED]" in saved["enrichment"]["narrative"]


class TestHeuristicFallback:
    def test_heuristic_passes_validation(self):
        profile = {
            "dimensions": {
                "signal_clarity": {"score": 80, "name": "Signal Clarity", "evidence": ["e1"]},
                "build_stability": {"score": 60, "name": "Build Stability", "evidence": []},
            },
            "workMode": {"dominant": {"id": "Prompt-Iterate", "line": "Iterates fast."}},
            "archetypes": [],
            "positioning": {
                "leverageMode": {"current": "harnessing"},
                "buildDomain": {"primary": "products"},
                "techDomains": [{"name": "python", "weight": 0.8}],
            },
            "wrappedStats": {"tools": ["Claude Code"]},
            "growthEdge": {"suggestion": "Try a dispatched subagent.", "context": "delegation"},
        }
        enr = build_heuristic_enrichment(profile)
        valid, err = validate_enrichment(enr)
        assert valid, err
        assert enr["source"] == "heuristic"


# ── v2 prompt: calibration directives present, signals carry inputs ─────────


def test_v2_prompt_directives_present():
    from nextmillionai.enrichment import build_enrichment_prompt

    prompt = build_enrichment_prompt({"confidence": 80}, "mode", "arch", [])
    # AI-integration work is first-class
    assert "AI-INTEGRATION WORK IS FIRST-CLASS" in prompt
    assert "buildDomainDistribution" in prompt
    # technical calibration bar
    assert "TECHNICAL CALIBRATION" in prompt
    # low-data honesty mode
    assert "LOW DATA = SMALLER CLAIMS" in prompt
    assert "Limited evidence so" in " ".join(prompt.split())
    assert "Limited evidence so far:" in " ".join(prompt.split())
    # pointer rule covers every claim class
    assert "EVERY strengths claim" in prompt


def test_v2_prompt_keeps_six_block_contract_and_rules():
    from nextmillionai.enrichment import build_enrichment_prompt

    prompt = build_enrichment_prompt({}, "m", "a", [])
    for block in (
        '"narrative"',
        '"positioningLine"',
        '"whatYouBuilt"',
        '"decisionPatterns"',
        '"strengths"',
        '"growthAreas"',
        '"howYouUseAI"',
    ):
        assert block in prompt
    assert "NO FABRICATION" in prompt
    assert "narrate them, never reassign" in prompt


# ── Generation pipeline: diverse excerpts + the evidence bank ──


class _FakeSession:
    def __init__(self, sid, tool, project, msgs, started=None, tasks=0):
        from datetime import datetime

        self.session_id = sid
        self.tool = tool
        self.project_path = project
        self.user_msgs = msgs
        self.started_at = datetime.fromisoformat(started) if started else None
        self.tool_calls_by_type = {"task": tasks, "bash": 2} if tasks else {"bash": 2}
        self.prompt_word_counts = [40, 60]
        self.models = ["m1"]
        self.extras = {"subagentRuns": tasks}


def _fake_sessions():
    return [
        _FakeSession("a", "claude_code", "/w/alpha", 90, "2026-01-05T10:00"),
        _FakeSession("b", "claude_code", "/w/alpha", 80, "2026-02-01T10:00"),
        _FakeSession("c", "cursor", "/w/beta", 5, "2026-06-10T10:00"),
        _FakeSession("d", "codex", "/w/gamma", 8, "2026-06-11T10:00", tasks=6),
        _FakeSession("e", "claude_code", "/w/delta", 3, "2026-03-01T10:00"),
    ]


def test_excerpts_are_diverse_not_just_longest():
    from nextmillionai.enrichment import select_excerpts

    ex = select_excerpts(_fake_sessions(), max_excerpts=4)
    projects = {e["project"] for e in ex}
    # longest-only would pick alpha twice and stop; diversity must reach
    # recent + dispatch-heavy sessions in other projects
    assert len(projects) >= 3
    assert any(e["subagentRuns"] for e in ex), "dispatch-heavy session missing"


def test_excerpts_carry_dates_as_pointers():
    from nextmillionai.enrichment import select_excerpts

    ex = select_excerpts(_fake_sessions(), max_excerpts=4)
    assert all(e["date"] for e in ex)
    assert all(e["summary"].startswith(f"Session {e['date']} in ") for e in ex)


def _bank_inputs():
    scan = {
        "git": {
            "projects": [
                {
                    "name": "alpha",
                    "path": "/Users/someone/w/alpha",
                    "languages": ["TypeScript", "Python"],
                    "commits_6m": 40,
                    "aiFrameworks": ["Anthropic SDK"],
                },
                {
                    "name": "quiet",
                    "path": "/Users/someone/w/quiet",
                    "languages": ["Go"],
                    "commits_6m": 1,
                    "aiFrameworks": [],
                },
            ]
        },
        "code_intel": {
            "available": True,
            "repos": [
                {
                    "name": "alpha",
                    "buildDomain": {
                        "domain": "ai_products",
                        "evidence": "monorepo: apps/gateway calls anthropic client",
                    },
                    "packages": ["apps/gateway", "packages/core"],
                }
            ],
        },
        "cursor": {
            "scored_commits": {
                "recentCommits": [
                    {"hash": "abc12345", "message": "gateway: stream tool results", "aiPct": 90}
                ]
            }
        },
    }
    profile = {
        "dimensions": {
            "signal_clarity": {"score": 80, "evidence": ["100% acceptance", "12 turns avg"]}
        }
    }
    return scan, profile


def test_evidence_bank_builds_citable_pointers():
    from nextmillionai.enrichment import build_evidence_bank

    bank = build_evidence_bank(*_bank_inputs())
    alpha = next(r for r in bank["repos"] if r["repo"] == "alpha")
    assert alpha["buildDomain"] == "ai_products"
    assert "apps/gateway" in alpha["packages"]
    assert bank["recentCommits"][0]["hash"] == "abc12345"
    assert bank["dimensionEvidence"]["signal_clarity"] == ["100% acceptance", "12 turns avg"]
    # a 1-commit repo with no AI deps and no verdict is not pointer material
    assert all(r["repo"] != "quiet" for r in bank["repos"])
    # derived-only: repo names, never filesystem paths
    assert "/Users/" not in json.dumps(bank)


def test_prompt_embeds_bank_and_sourcing_rule():
    from nextmillionai.enrichment import build_enrichment_prompt, build_evidence_bank

    bank = build_evidence_bank(*_bank_inputs())
    prompt = build_enrichment_prompt({}, "m", "a", [], bank)
    assert "EVIDENCE BANK" in prompt
    assert '"buildDomain": "ai_products"' in prompt
    assert "never invent a pointer" in prompt
    # bank omitted (old callers) still renders a valid prompt
    assert "{{EVIDENCE_BANK}}" not in build_enrichment_prompt({}, "m", "a", [])


def test_generated_prompt_file_carries_generated_banner():
    """The on-disk prompt is an artifact, not a source: the banner names
    the real sources so neither a human nor an agent edits the output
    (the template itself must NOT carry it — it IS the source)."""
    from pathlib import Path

    from nextmillionai.enrichment import GENERATED_BANNER, prompt_file_text

    assert "@generated" in GENERATED_BANNER
    assert "DO NOT EDIT" in GENERATED_BANNER
    assert "ENRICHMENT-PROMPT.md" in GENERATED_BANNER
    assert "enrichment.py" in GENERATED_BANNER
    on_disk = prompt_file_text("PROMPT BODY")
    assert on_disk.startswith(GENERATED_BANNER) and on_disk.endswith("PROMPT BODY")
    template = (Path(__file__).parent.parent / "ENRICHMENT-PROMPT.md").read_text()
    assert "@generated" not in template
