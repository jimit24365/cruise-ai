"""Tests for the static export artifact.

Privacy invariants: the artifact contains only the redacted shareable
JSON; experimental/coverage/anti-patterns/growth/hidden projects/raw
prompts never appear; filesystem paths never leak; visibility config
is honored; both views ship and point at the same ./assessment.json.
"""

import json

import pytest

import nextmillionai.paths as paths_mod
from nextmillionai.export import export_static, verify_artifact_json


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path / "home"))
    return tmp_path


def write_profile(extra=None):
    profile = {
        "schema_version": "1.0",
        "name": "Test Builder",
        "composite": 70,
        "intent_score": 70,
        "dimensions": {
            "signal_clarity": {
                "score": 70,
                "name": "Signal Clarity",
                "weight": 0.18,
                "evidence": [],
            }
        },
        "archetypes": [],
        "titles": [],
        "assessment": {
            "confidence": 80,
            "sessions": 30,
            "dateRange": "x",
            "sources_used": ["Claude Code"],
            "privacyMode": "local-only",
        },
        "positioning": {
            "leverageMode": {"current": "harnessing"},
            "buildDomain": {"primary": "products"},
            "techDomains": [],
        },
        "activity": {"streak": 3, "activeDays": 10, "days": []},
        "wrappedStats": {"goToPrompt": "my secret prompt", "tools": []},
        "enrichment": {"narrative": "n", "growthAreas": [{"observed": "private"}]},
        "experimental": {"available": True, "signals": [{"label": "x"}], "codeIntelligence": []},
        "coverage": {"gaps": [{"source": "cursor"}]},
        "antiPatterns": [{"name": "private"}],
        "growthEdge": {"suggestion": "private"},
        "scannedProjects": [{"name": "secret-project", "path": "/Users/x/secret"}],
    }
    if extra:
        profile.update(extra)
    p = paths_mod.profile_path()
    p.write_text(json.dumps(profile))
    return profile


class TestExportStatic:
    def test_requires_assessment(self, fake_home, tmp_path):
        with pytest.raises(RuntimeError, match="No assessment"):
            export_static(tmp_path / "out")

    def test_artifact_structure(self, fake_home, tmp_path):
        write_profile()
        summary = export_static(tmp_path / "out")
        files = summary["files"]
        assert "index.html" in files
        assert "report.html" in files
        assert "assessment.json" in files
        assert any(f.startswith("static/css/") for f in files)
        assert any(f.startswith("static/js/") for f in files)

    def test_private_fields_never_exported(self, fake_home, tmp_path):
        write_profile()
        export_static(tmp_path / "out")
        artifact = json.loads((tmp_path / "out" / "assessment.json").read_text())
        dumped = json.dumps(artifact)
        assert "experimental" not in artifact
        assert "coverage" not in artifact
        assert "antiPatterns" not in artifact
        assert "growthEdge" not in artifact
        assert "scannedProjects" not in artifact
        assert "my secret prompt" not in dumped
        assert "secret-project" not in dumped
        assert "growthAreas" not in dumped
        assert "/Users/" not in dumped

    def test_html_paths_rewritten_for_static(self, fake_home, tmp_path):
        write_profile()
        export_static(tmp_path / "out")
        index = (tmp_path / "out" / "index.html").read_text()
        report = (tmp_path / "out" / "report.html").read_text()
        assert 'href="/static/' not in index
        assert "./static/" in index
        # The flip travels via tabs-shared.js (nmaFlipTo uses sibling-file
        # hrefs in export mode) — the shared module must ship in the artifact
        assert "tabs-shared.js" in index and "tabs-shared.js" in report
        # the flip is the segmented toggle (nmaFlipTo handles export mode);
        # no absolute same-site hrefs may survive in the artifact
        assert 'href="/profile"' not in report and 'href="/report"' not in index
        assert 'id="segProfile"' in report and 'id="segReport"' in index

    def test_both_views_read_same_assessment_json(self, fake_home, tmp_path):
        write_profile()
        export_static(tmp_path / "out")
        profile_js = (tmp_path / "out" / "static" / "js" / "profile.js").read_text()
        report_js = (tmp_path / "out" / "static" / "js" / "report.js").read_text()
        assert "./assessment.json" in profile_js
        assert "./assessment.json" in report_js


class TestVerifyArtifact:
    def test_clean_artifact_passes(self):
        assert verify_artifact_json({"composite": 70, "dimensions": {}}) == []

    def test_forbidden_key_flagged(self):
        violations = verify_artifact_json({"experimental": {"signals": []}})
        assert violations

    def test_nested_forbidden_key_flagged(self):
        violations = verify_artifact_json({"a": {"b": {"goToPrompt": "x"}}})
        assert violations

    def test_filesystem_path_flagged(self):
        violations = verify_artifact_json({"p": "/Users/someone/repo"})
        assert violations
