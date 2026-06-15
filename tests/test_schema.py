"""Tests for the nextmillionai data-contract schema."""

import re
import warnings

from nextmillionai.schema import (
    SCHEMA_VERSION,
    SHAREABLE_PROFILE_FIELDS,
    TAXONOMY_VERSION,
    build_shareable_profile,
    validate_schema_version,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_full_profile(**overrides):
    """Build a realistic profile dict with sensitive fields injected."""
    profile = {
        "schema_version": SCHEMA_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        # Identity
        "name": "Jane Doe",
        "title": "Senior Engineer",
        "experience_years": 8,
        "ai_experience_years": 2,
        "location": "San Francisco, CA",
        "work_style": "iterative",
        "notice_period": "2 weeks",
        "stack": ["Python", "React"],
        "projects": [
            {"name": "myapp", "desc": "A web app", "path": "/Users/jane/myapp"},
        ],
        # Scores
        "intent_score": 78,
        "composite": 78,
        "dimensions": {
            "signal_clarity": {
                "score": 82,
                "evidence": ["82% first-shot"],
                "name": "Signal Clarity",
                "weight": 0.18,
                "description": "...",
            },
        },
        "archetypes": [
            {
                "id": "context_engineer",
                "name": "Context Engineer",
                "icon": "\u2386",
                "color": "#818cf8",
                "description": "Masters context",
                "soughtBy": "AI teams",
                "score": 84,
                "level": {"id": "advanced", "label": "Advanced", "color": "#67e8f9"},
                "evidence": ["28 specs"],
            },
        ],
        "titles": [
            {
                "id": "context_architect",
                "name": "Context Architect",
                "tagline": "Engineers AI context",
                "idealFor": "AI teams",
                "emoji": "\u2386",
                "rare": False,
                "legendary": False,
            },
        ],
        "primaryTitle": {
            "id": "context_architect",
            "name": "Context Architect",
            "tagline": "Engineers AI context",
            "idealFor": "AI teams",
            "emoji": "\u2386",
            "rare": False,
            "legendary": False,
        },
        "workMode": {
            "dominant": {"id": "One-Shot-Verify", "line": "Fires one prompt, verifies, ships."},
            "secondary": [{"id": "Prompt-Iterate", "line": "Quick hypothesis loops."}],
        },
        "antiPatterns": [],
        "trajectory": {"id": "stable", "label": "Stable", "description": "Consistent."},
        "map": {
            "x": 42.0,
            "y": 65.0,
            "xLabel": ["Explorer", "Architect"],
            "yLabel": ["Solo", "Orchestrator"],
        },
        "growthEdge": {"suggestion": "Pin key context files.", "context": "One-Shot-Verify"},
        "wrappedStats": {
            "maxParallelAgents": 3,
            "longestSessionMinutes": 142,
            "goToPrompt": "fix the login bug using jwt",
            "tools": ["claude", "cursor"],
            "models": ["claude-4.6-opus"],
            "workMode": "Fires one prompt, verifies, ships.",
        },
        "dataCompleteness": 1.0,
        "tools_detected": ["claude_code"],
        "signals": {"ai_code_blocks": 8500, "scored_commits": 89},
        "verification": {"source": "claude_code", "verified": True},
        "scoredAt": 1717718400.0,
        # --- Sensitive fields that should NOT survive stripping ---
        "_raw_prompts": ["fix the bug in auth.py"],
        "_conversation_titles": ["Implement JWT auth flow"],
        "_file_paths": ["/Users/jane/projects/myapp/src/auth.py"],
        "category": "advanced",  # legacy field, not in allowlist
    }
    profile.update(overrides)
    return profile


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestBuildShareableProfile:
    def test_only_allowed_fields_present(self):
        """Shareable profile must only contain SHAREABLE_PROFILE_FIELDS keys."""
        profile = _make_full_profile()
        shareable = build_shareable_profile(profile)
        extra = set(shareable.keys()) - SHAREABLE_PROFILE_FIELDS
        assert extra == set(), f"Unexpected fields in shareable profile: {extra}"

    def test_strips_sensitive_fields(self):
        """Fields not in the allowlist are removed."""
        profile = _make_full_profile()
        shareable = build_shareable_profile(profile)
        assert "_raw_prompts" not in shareable
        assert "_conversation_titles" not in shareable
        assert "_file_paths" not in shareable
        assert "category" not in shareable

    def test_projects_scrubbed_to_name_desc(self):
        """Project entries must contain only 'name' and 'desc', no 'path'."""
        profile = _make_full_profile()
        shareable = build_shareable_profile(profile)
        for proj in shareable["projects"]:
            assert set(proj.keys()) == {"name", "desc"}, f"Project has extra keys: {proj.keys()}"
            assert "path" not in proj

    def test_no_filesystem_paths_in_values(self):
        """No value in the shareable profile should look like a filesystem path."""
        profile = _make_full_profile()
        shareable = build_shareable_profile(profile)

        path_pattern = re.compile(r"(/Users/|/home/|/tmp/|C:\\|/var/)")

        def check_value(v, breadcrumb=""):
            if isinstance(v, str):
                assert not path_pattern.search(v), f"Filesystem path found at {breadcrumb}: {v!r}"
            elif isinstance(v, dict):
                for k, val in v.items():
                    check_value(val, f"{breadcrumb}.{k}")
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    check_value(item, f"{breadcrumb}[{i}]")

        for key, value in shareable.items():
            check_value(value, key)

    def test_schema_version_always_present(self):
        """build_shareable_profile always sets schema_version."""
        profile = _make_full_profile()
        del profile["schema_version"]
        shareable = build_shareable_profile(profile)
        assert shareable["schema_version"] == SCHEMA_VERSION

    def test_empty_profile(self):
        """Stripping an empty dict returns only schema_version."""
        shareable = build_shareable_profile({})
        assert shareable == {"schema_version": SCHEMA_VERSION}

    def test_preserves_all_shareable_fields(self):
        """All expected shareable fields survive stripping."""
        profile = _make_full_profile()
        shareable = build_shareable_profile(profile)
        expected = SHAREABLE_PROFILE_FIELDS & set(profile.keys())
        for field in expected:
            assert field in shareable, f"Shareable field {field!r} was dropped"


class TestValidateSchemaVersion:
    def test_valid_version_no_warning(self):
        """No warning when schema_version matches."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            validate_schema_version({"schema_version": SCHEMA_VERSION}, "test")
            assert len(w) == 0

    def test_missing_version_warns(self):
        """Warning when schema_version is absent (pre-1.0 data)."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            validate_schema_version({}, "test")
            assert len(w) == 1
            assert "no schema_version" in str(w[0].message)

    def test_wrong_version_warns(self):
        """Warning when schema_version doesn't match expected."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            validate_schema_version({"schema_version": "99.0"}, "test")
            assert len(w) == 1
            assert "99.0" in str(w[0].message)


class TestPrivacyGoToPrompt:
    """Ensure raw prompt text never leaks into the shareable profile."""

    def test_go_to_prompt_stripped_from_shareable(self):
        """wrappedStats.goToPrompt must be removed by build_shareable_profile."""
        profile = _make_full_profile()
        shareable = build_shareable_profile(profile)
        ws = shareable.get("wrappedStats", {})
        assert "goToPrompt" not in ws, "goToPrompt leaked into shareable profile"

    def test_wrapped_stats_other_fields_survive(self):
        """Non-sensitive wrappedStats fields survive stripping."""
        profile = _make_full_profile()
        shareable = build_shareable_profile(profile)
        ws = shareable.get("wrappedStats", {})
        assert ws.get("maxParallelAgents") == 3
        assert ws.get("tools") == ["claude", "cursor"]
        assert ws.get("workMode") is not None

    def test_no_raw_prompt_text_anywhere(self):
        """Scan the entire shareable profile for raw prompt-like text."""
        profile = _make_full_profile()
        shareable = build_shareable_profile(profile)

        # The goToPrompt value from the fixture
        raw_prompt = "fix the login bug using jwt"

        def check_no_prompt(v, breadcrumb=""):
            if isinstance(v, str):
                assert raw_prompt not in v.lower(), f"Raw prompt text found at {breadcrumb}: {v!r}"
            elif isinstance(v, dict):
                for k, val in v.items():
                    check_no_prompt(val, f"{breadcrumb}.{k}")
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    check_no_prompt(item, f"{breadcrumb}[{i}]")

        for key, value in shareable.items():
            check_no_prompt(value, key)

    def test_new_v020_fields_in_shareable(self):
        """workMode, map, wrappedStats are in SHAREABLE_PROFILE_FIELDS.
        growthEdge and antiPatterns are intentionally EXCLUDED (private)."""
        for field in ("workMode", "map", "wrappedStats", "taxonomy_version"):
            assert field in SHAREABLE_PROFILE_FIELDS, (
                f"{field!r} missing from SHAREABLE_PROFILE_FIELDS"
            )
        # growthEdge and antiPatterns are private — Step 4 requirement
        assert "growthEdge" not in SHAREABLE_PROFILE_FIELDS
        assert "antiPatterns" not in SHAREABLE_PROFILE_FIELDS

    def test_new_v020_fields_survive_stripping(self):
        """New v0.2.0 fields survive build_shareable_profile (except private ones)."""
        profile = _make_full_profile()
        shareable = build_shareable_profile(profile)
        assert "workMode" in shareable
        assert "map" in shareable
        assert "wrappedStats" in shareable
        assert "taxonomy_version" in shareable
        # growthEdge and antiPatterns are PRIVATE — not in shareable
        assert "growthEdge" not in shareable
        assert "antiPatterns" not in shareable


class TestEndToEndScoreProfile:
    """Integration test: score_profile → validate against schema → no raw text."""

    def test_score_profile_validates_against_schema(self):
        """score_profile output contains all expected Profile fields."""
        from nextmillionai.scoring import score_profile

        scan_results = {
            "normalized": {
                "totalSessions": 50,
                "totalScoredCommits": 20,
                "totalAiCodeBlocks": 500,
                "projectCount": 3,
                "aiUsageSpanDays": 90,
                "modelCount": 2,
                "planCount": 10,
                "languageCount": 3,
                "firstShotAcceptRate": 0.7,
                "leverageRatio": 12,
                "agentModeRatio": 0.6,
                "avgTurnsPerTask": 3.5,
                "filesPerSession": 5,
                "avgPromptWords": 40,
                "primaryModel": "claude-4.6-opus",
                "cliAiTools": ["claude"],
                "cliAiToolCount": 1,
                "cliAiCommandCount": 20,
                "uniqueToolCount": 4,
                "mcpServerCount": 2,
                "maxParallelAgents": 3,
                "mcpToolCalls": 15,
                "deepSessionCount": 8,
                "fileReadToEditRatio": 2.5,
                "featureToFixRatio": 1.8,
                "planModePercent": 0.2,
                "composerRatio": 0.5,
                "terminalCommandCount": 50,
                "testAfterAiRate": 0.3,
                "postAiEditRate": 0.15,
                "aiLineSurvivalRate": 0.85,
                "errorFixRate": 0.9,
                "referenceUsageRate": 0.3,
                "buildSuccessRate": 0.8,
            }
        }

        profile = score_profile(scan_results)

        # Structural checks against schema.py Profile TypedDict keys
        assert profile["schema_version"] == SCHEMA_VERSION
        assert profile["taxonomy_version"] == TAXONOMY_VERSION
        assert isinstance(profile["composite"], (int, type(None)))
        assert isinstance(profile["dimensions"], dict)
        assert len(profile["dimensions"]) == 6
        assert isinstance(profile["archetypes"], list)
        assert len(profile["archetypes"]) == 9
        assert isinstance(profile["titles"], list)
        assert isinstance(profile["workMode"], dict)
        assert "dominant" in profile["workMode"]
        assert "secondary" in profile["workMode"]
        assert isinstance(profile["map"], dict)
        assert {"x", "y", "xLabel", "yLabel"} <= set(profile["map"].keys())
        assert isinstance(profile["growthEdge"], dict)
        assert "suggestion" in profile["growthEdge"]
        assert isinstance(profile["wrappedStats"], dict)
        assert isinstance(profile["antiPatterns"], list)
        assert isinstance(profile["trajectory"], dict)
        assert isinstance(profile["dataCompleteness"], float)
        assert isinstance(profile["scoredAt"], float)

    def test_score_profile_shareable_has_no_raw_text(self):
        """Shareable version of a scored profile contains no raw prompt/code text."""
        from nextmillionai.scoring import score_profile

        scan_results = {
            "normalized": {
                "totalSessions": 50,
                "agentModeRatio": 0.6,
                "primaryModel": "claude-4.6-opus",
            }
        }
        profile = score_profile(scan_results)
        shareable = build_shareable_profile(profile)

        # No goToPrompt
        ws = shareable.get("wrappedStats", {})
        assert "goToPrompt" not in ws

        # No filesystem paths
        path_re = re.compile(r"(/Users/|/home/|/tmp/|C:\\|/var/)")

        def check_path(v, breadcrumb=""):
            if isinstance(v, str):
                assert not path_re.search(v), f"Filesystem path found at {breadcrumb}: {v!r}"
            elif isinstance(v, dict):
                for k, val in v.items():
                    check_path(val, f"{breadcrumb}.{k}")
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    check_path(item, f"{breadcrumb}[{i}]")

        for key, value in shareable.items():
            check_path(value, key)


class TestNewViewFields:
    """Tests for the front-end view data fields added to schema."""

    def test_view_fields_in_shareable_allowlist(self):
        """summaryLine, activityByDay, stackSummary, modelsSummary are shareable."""
        for field in ("summaryLine", "activityByDay", "stackSummary", "modelsSummary"):
            assert field in SHAREABLE_PROFILE_FIELDS, (
                f"{field!r} missing from SHAREABLE_PROFILE_FIELDS"
            )

    def test_scanned_projects_excluded_from_shareable(self):
        """scannedProjects must NOT be in SHAREABLE_PROFILE_FIELDS (project names
        are user-controlled visibility)."""
        assert "scannedProjects" not in SHAREABLE_PROFILE_FIELDS

    def test_view_fields_survive_stripping(self):
        """View fields present in profile survive build_shareable_profile."""
        profile = _make_full_profile(
            summaryLine="Ships in One Shot Verify mode.",
            compositeLabel="strength index \u2014 One-Shot-Verify",
            dominantMode="One-Shot-Verify",
            activityByDay=[{"date": "2024-06-01", "sessions": 2}],
            scannedProjects=[{"name": "myapp", "sessionCount": 5}],
            stackSummary={"languages": {"Python": 0.7}, "frameworks": ["FastAPI"]},
            modelsSummary={"byModel": {"claude-opus-4-6": 10}, "primaryModel": "claude-opus-4-6"},
        )
        shareable = build_shareable_profile(profile)
        assert shareable.get("summaryLine") == "Ships in One Shot Verify mode."
        assert shareable.get("compositeLabel") is not None
        assert shareable.get("dominantMode") is not None
        assert shareable.get("activityByDay") is not None
        assert shareable.get("stackSummary") is not None
        assert shareable.get("modelsSummary") is not None
        # scannedProjects should be stripped
        assert "scannedProjects" not in shareable

    def test_no_synthetic_in_view_fields(self):
        """View fields must never contain '<synthetic>'."""
        profile = _make_full_profile(
            summaryLine="Ships in One Shot Verify mode.",
            activityByDay=[{"date": "2024-06-01", "sessions": 2}],
            stackSummary={"languages": {"Python": 1.0}, "frameworks": []},
            modelsSummary={"byModel": {"claude-opus-4-6": 5}, "primaryModel": "claude-opus-4-6"},
        )
        shareable = build_shareable_profile(profile)

        def check_no_synthetic(v, breadcrumb=""):
            if isinstance(v, str):
                assert "<synthetic>" not in v, f"<synthetic> found at {breadcrumb}: {v!r}"
            elif isinstance(v, dict):
                for k, val in v.items():
                    check_no_synthetic(val, f"{breadcrumb}.{k}")
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    check_no_synthetic(item, f"{breadcrumb}[{i}]")

        for key, value in shareable.items():
            check_no_synthetic(value, key)

    def test_compositeLabel_and_dominantMode_shareable(self):
        """compositeLabel and dominantMode are in the shareable allowlist."""
        for field in ("compositeLabel", "dominantMode"):
            assert field in SHAREABLE_PROFILE_FIELDS, (
                f"{field!r} missing from SHAREABLE_PROFILE_FIELDS"
            )
