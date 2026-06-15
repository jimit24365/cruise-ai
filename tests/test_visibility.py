"""Tests for the visibility config module."""

from __future__ import annotations

import pytest

from nextmillionai.schema import build_shareable_profile
from nextmillionai.visibility import (
    VALID_SECTION_IDS,
    default_visibility_config,
    load_visibility_config,
    save_visibility_config,
    validate_visibility_config,
)


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    """Point NEXTMILLIONAI_HOME to a temp dir so tests don't touch real data."""
    monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path))


# ── Default config ───────────────────────────────────────────────────────────


class TestDefaultConfig:
    def test_has_all_sections(self):
        cfg = default_visibility_config()
        assert set(cfg["sections"].keys()) == VALID_SECTION_IDS

    def test_all_visible_by_default(self):
        from nextmillionai.visibility import PRIVATE_BY_DEFAULT_SECTIONS

        cfg = default_visibility_config()
        for sid, flags in cfg["sections"].items():
            assert flags["showOnPage"] is True, sid
            expected = sid not in PRIVATE_BY_DEFAULT_SECTIONS
            assert flags["includeInShareable"] is expected, sid

    def test_growth_areas_private_by_default(self):
        cfg = default_visibility_config()
        assert cfg["sections"]["growthAreas"]["includeInShareable"] is False

    def test_growth_areas_shareable_on_explicit_opt_in(self):
        from nextmillionai.schema import build_shareable_profile

        profile = {
            "schema_version": "1.0",
            "enrichment": {"narrative": "n", "growthAreas": [{"observed": "g"}]},
        }
        default = build_shareable_profile(profile, default_visibility_config())
        assert "growthAreas" not in default.get("enrichment", {})

        opted = default_visibility_config()
        opted["sections"]["growthAreas"]["includeInShareable"] = True
        shared = build_shareable_profile(profile, opted)
        assert shared["enrichment"]["growthAreas"] == [{"observed": "g"}]

    def test_hidden_lists_empty(self):
        cfg = default_visibility_config()
        assert cfg["hiddenProjects"] == []
        assert cfg["hiddenDimensions"] == []


# ── Validation ───────────────────────────────────────────────────────────────


class TestValidation:
    def test_valid_config_passes(self):
        cfg = default_visibility_config()
        assert validate_visibility_config(cfg) == []

    def test_empty_dict_is_valid(self):
        assert validate_visibility_config({}) == []

    def test_unknown_top_key_rejected(self):
        errors = validate_visibility_config({"scoring": True})
        assert any("unknown keys" in e for e in errors)

    def test_invalid_section_id_rejected(self):
        errors = validate_visibility_config({"sections": {"bogus_section": {"showOnPage": True}}})
        assert any("invalid section" in e.lower() for e in errors)

    def test_invalid_flag_key_rejected(self):
        errors = validate_visibility_config({"sections": {"dimensions": {"visible": True}}})
        assert any("unknown flag" in e for e in errors)

    def test_non_bool_flag_rejected(self):
        errors = validate_visibility_config({"sections": {"dimensions": {"showOnPage": "yes"}}})
        assert any("boolean" in e for e in errors)

    def test_invalid_dimension_id_rejected(self):
        errors = validate_visibility_config({"hiddenDimensions": ["signal_clarity", "fake_dim"]})
        assert any("invalid dimension" in e.lower() for e in errors)

    def test_hidden_projects_must_be_strings(self):
        errors = validate_visibility_config({"hiddenProjects": [123]})
        assert any("string" in e for e in errors)

    def test_sections_must_be_object(self):
        errors = validate_visibility_config({"sections": "all"})
        assert any("object" in e for e in errors)


# ── Round-trip persistence ───────────────────────────────────────────────────


class TestPersistence:
    def test_save_and_load_roundtrip(self):
        cfg = default_visibility_config()
        cfg["sections"]["dimensions"]["includeInShareable"] = False
        cfg["hiddenProjects"] = ["secret-app"]
        cfg["hiddenDimensions"] = ["signal_clarity"]
        save_visibility_config(cfg)

        loaded = load_visibility_config()
        assert loaded["sections"]["dimensions"]["includeInShareable"] is False
        assert loaded["hiddenProjects"] == ["secret-app"]
        assert loaded["hiddenDimensions"] == ["signal_clarity"]
        # Other sections remain default
        assert loaded["sections"]["archetypes"]["includeInShareable"] is True

    def test_load_returns_defaults_when_no_file(self):
        loaded = load_visibility_config()
        assert loaded == default_visibility_config()

    def test_save_rejects_invalid_config(self):
        with pytest.raises(ValueError, match="invalid section"):
            save_visibility_config({"sections": {"bad": {"showOnPage": True}}})

    def test_partial_update_merges_with_defaults(self):
        partial = {"sections": {"archetypes": {"showOnPage": False}}}
        save_visibility_config(partial)
        loaded = load_visibility_config()
        assert loaded["sections"]["archetypes"]["showOnPage"] is False
        # Unmentioned flag keeps default
        assert loaded["sections"]["archetypes"]["includeInShareable"] is True
        # Unmentioned sections keep defaults
        assert loaded["sections"]["dimensions"]["showOnPage"] is True


# ── Shareable profile filtering ──────────────────────────────────────────────


def _stub_profile():
    """Minimal profile with fields that shareable builder keeps."""
    return {
        "schema_version": "1.0",
        "name": "Dev",
        "title": "Engineer",
        "intent_score": 80,
        "composite": 80,
        "dimensions": {
            "signal_clarity": {
                "score": 85,
                "evidence": [],
                "name": "Signal Clarity",
                "weight": 0.18,
                "description": "",
            },
            "build_stability": {
                "score": 70,
                "evidence": [],
                "name": "Build Stability",
                "weight": 0.22,
                "description": "",
            },
            "decision_weight": {
                "score": 60,
                "evidence": [],
                "name": "Decision Weight",
                "weight": 0.18,
                "description": "",
            },
        },
        "archetypes": [
            {
                "id": "agent_builder",
                "name": "Agent Builder",
                "icon": "A",
                "color": "#000",
                "description": "",
                "soughtBy": "",
                "score": 80,
                "level": {"id": "a", "label": "A", "color": "#000"},
                "evidence": [],
            },
        ],
        "titles": [
            {
                "id": "t1",
                "name": "Title One",
                "tagline": "",
                "idealFor": "",
                "emoji": "",
                "rare": False,
                "legendary": False,
            },
        ],
        "primaryTitle": {
            "id": "t1",
            "name": "Title One",
            "tagline": "",
            "idealFor": "",
            "emoji": "",
            "rare": False,
            "legendary": False,
        },
        "workMode": {"dominant": {"id": "One-Shot-Verify", "line": "..."}, "secondary": []},
        "compositeLabel": "strength index",
        "dominantMode": "One-Shot-Verify",
        "antiPatterns": [],
        "trajectory": {"id": "stable", "label": "Stable", "description": ""},
        "map": {"x": 50, "y": 50, "xLabel": [], "yLabel": []},
        "growthEdge": {"suggestion": "Try more tools", "context": ""},
        "wrappedStats": {"maxParallelAgents": 3},
        "dataCompleteness": 0.8,
        "tools_detected": ["claude_code"],
        "signals": {"ai_code_blocks": 100, "scored_commits": 50},
        "verification": {"source": "claude_code", "verified": True},
        "scoredAt": 1700000000.0,
        "summaryLine": "Ships One Shot Verify",
        "activityByDay": [{"date": "2024-06-01", "sessions": 1}],
        "stackSummary": {"languages": {"Python": 1.0}, "frameworks": []},
        "modelsSummary": {"byModel": {"opus": 10}, "primaryModel": "opus"},
        "projects": [
            {"name": "my-app", "desc": "Main app"},
            {"name": "secret-app", "desc": "Private project"},
        ],
    }


class TestShareableWithVisibility:
    def test_no_visibility_keeps_all(self):
        profile = _stub_profile()
        shareable = build_shareable_profile(profile)
        assert "dimensions" in shareable
        assert "archetypes" in shareable
        assert "activityByDay" in shareable

    def test_hidden_section_omitted(self):
        vis = default_visibility_config()
        vis["sections"]["archetypes"]["includeInShareable"] = False
        shareable = build_shareable_profile(_stub_profile(), visibility=vis)
        assert "archetypes" not in shareable
        # Other sections still present
        assert "dimensions" in shareable

    def test_hidden_titles_removes_primary_title(self):
        vis = default_visibility_config()
        vis["sections"]["titles"]["includeInShareable"] = False
        shareable = build_shareable_profile(_stub_profile(), visibility=vis)
        assert "titles" not in shareable
        assert "primaryTitle" not in shareable

    def test_hidden_work_mode_removes_composite_label(self):
        vis = default_visibility_config()
        vis["sections"]["workMode"]["includeInShareable"] = False
        shareable = build_shareable_profile(_stub_profile(), visibility=vis)
        assert "workMode" not in shareable
        assert "compositeLabel" not in shareable
        assert "dominantMode" not in shareable

    def test_hidden_project_filtered(self):
        vis = default_visibility_config()
        vis["hiddenProjects"] = ["secret-app"]
        shareable = build_shareable_profile(_stub_profile(), visibility=vis)
        names = [p["name"] for p in shareable["projects"]]
        assert "my-app" in names
        assert "secret-app" not in names

    def test_hidden_dimension_filtered(self):
        vis = default_visibility_config()
        vis["hiddenDimensions"] = ["signal_clarity"]
        shareable = build_shareable_profile(_stub_profile(), visibility=vis)
        assert "signal_clarity" not in shareable["dimensions"]
        assert "build_stability" in shareable["dimensions"]

    def test_shareable_still_enforces_allowlist(self):
        """Visibility config cannot add fields outside the allowlist."""
        profile = _stub_profile()
        profile["raw_secret"] = "should never appear"
        vis = default_visibility_config()
        shareable = build_shareable_profile(profile, visibility=vis)
        assert "raw_secret" not in shareable

    def test_empty_visibility_same_as_none(self):
        profile = _stub_profile()
        base = build_shareable_profile(profile)
        with_empty = build_shareable_profile(profile, visibility={})
        assert base == with_empty

    def test_multiple_hidden_dimensions(self):
        vis = default_visibility_config()
        vis["hiddenDimensions"] = ["signal_clarity", "build_stability"]
        shareable = build_shareable_profile(_stub_profile(), visibility=vis)
        assert "signal_clarity" not in shareable["dimensions"]
        assert "build_stability" not in shareable["dimensions"]
        assert "decision_weight" in shareable["dimensions"]
