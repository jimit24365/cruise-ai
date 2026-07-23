"""Tests for the adapter registry and orchestration."""

from __future__ import annotations

import shutil
from pathlib import Path

from nextmillionai.adapters._registry import (
    _CONSENT_KEYS,
    get_git_adapter,
    get_session_adapters,
    run_adapters,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestGetAdapters:
    def test_session_adapters_returned(self):
        adapters = get_session_adapters()
        names = [a.name for a in adapters]
        # 5 first-class (incl. kiro) + 8 wider-field (other_tools group)
        assert len(adapters) >= 13
        assert "claude_code" in names
        assert "cursor" in names
        assert "codex" in names
        assert "kiro" in names
        assert "claude_desktop" in names  # experimental, consent default OFF
        for wider in (
            "aider",
            "cline",
            "continue",
            "copilot_chat",
            "windsurf",
            "zed_ai",
            "jetbrains_ai",
            "cody",
        ):
            assert wider in names

    def test_git_adapter_returned(self):
        adapter = get_git_adapter()
        assert adapter.name == "git"
        assert adapter.detect() is True


class TestConsentRegistryCompleteness:
    """The gate that kills the dead-wiring bug class: an adapter whose
    consent group is not a real consent key is silently never scanned
    (enabled_sources.get(unknown, False)) — exactly how the Kiro adapter
    first shipped registered but dead."""

    def test_every_adapter_consent_group_is_a_consent_key(self):
        from nextmillionai.consent import ALL_SOURCES

        for adapter in get_session_adapters():
            group = _CONSENT_KEYS.get(adapter.name, "other_tools")
            assert group in ALL_SOURCES, (
                f"adapter '{adapter.name}' resolves to consent group '{group}' "
                f"which is not in consent.ALL_SOURCES — it would be silently "
                f"gated OFF on every production scan"
            )

    def test_consent_keys_values_are_all_consent_keys(self):
        from nextmillionai.consent import ALL_SOURCES

        unknown = set(_CONSENT_KEYS.values()) - set(ALL_SOURCES)
        assert unknown == set(), f"_CONSENT_KEYS maps to unknown consent keys: {unknown}"

    def test_every_source_has_a_disclosure_block(self):
        """Informed consent: every ALL_SOURCES key must have a printed
        Read/Derived/Never disclosure paragraph."""
        from nextmillionai.consent import _DISCLOSURE_BLOCKS, ALL_SOURCES

        assert set(_DISCLOSURE_BLOCKS) == set(ALL_SOURCES)


class TestConsentDerivedScan:
    """Integration through the REAL consent path: prompt_consent output →
    run_adapters. This is the test that would have caught PR #4's bug —
    unit tests calling the adapter directly bypass the consent gate."""

    def _kiro_fixture(self, tmp_path: Path) -> Path:
        import json

        kiro_dir = tmp_path / ".kiro" / "sessions" / "cli"
        kiro_dir.mkdir(parents=True)
        sid = "itest-0000-0000-0000-000000000001"
        (kiro_dir / f"{sid}.json").write_text(
            json.dumps(
                {
                    "session_id": sid,
                    "cwd": "/Users/dev/proj",
                    "created_at": "2026-07-01T10:00:00.000000Z",
                    "updated_at": "2026-07-01T10:30:00.000000Z",
                    "session_created_reason": "user",
                    "session_state": {"agent_name": None},
                }
            )
        )
        (kiro_dir / f"{sid}.jsonl").write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "version": "v1",
                            "kind": "Prompt",
                            "data": {
                                "message_id": "m1",
                                "content": [{"kind": "text", "data": "fix the bug"}],
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "version": "v1",
                            "kind": "AssistantMessage",
                            "data": {
                                "message_id": "m2",
                                "content": [
                                    {
                                        "kind": "toolUse",
                                        "data": {"toolUseId": "t1", "name": "shell", "input": {}},
                                    }
                                ],
                            },
                        }
                    ),
                ]
            )
        )
        return kiro_dir

    def test_consent_derived_scan_includes_kiro(self, tmp_path, monkeypatch):
        import nextmillionai.scanner as scanner_mod
        from nextmillionai.consent import prompt_consent

        monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path))
        monkeypatch.setattr(scanner_mod, "KIRO_SESSIONS_DIR", self._kiro_fixture(tmp_path))
        monkeypatch.setattr(scanner_mod, "KIRO_IDE_DIRS", [])

        enabled = prompt_consent(non_interactive=True)
        enabled["git"] = False  # keep the test off the real filesystem
        sessions, raw, _ = run_adapters(enabled_sources=enabled)

        kiro_sessions = [s for s in sessions if s.tool == "kiro"]
        assert len(kiro_sessions) == 1
        assert raw["kiro"] is not None
        assert raw["kiro"]["total_sessions"] == 1

    def test_consent_off_suppresses_kiro(self, tmp_path, monkeypatch):
        import nextmillionai.scanner as scanner_mod
        from nextmillionai.consent import prompt_consent

        monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path))
        monkeypatch.setattr(scanner_mod, "KIRO_SESSIONS_DIR", self._kiro_fixture(tmp_path))
        monkeypatch.setattr(scanner_mod, "KIRO_IDE_DIRS", [])

        enabled = prompt_consent(non_interactive=True)
        enabled["kiro"] = False
        enabled["git"] = False
        sessions, raw, _ = run_adapters(enabled_sources=enabled)

        assert [s for s in sessions if s.tool == "kiro"] == []
        assert raw["kiro"] is None


class TestConsentGating:
    def test_disabled_source_not_scanned(self, tmp_path):
        """When a source is disabled, its adapter is not run."""
        projects_dir = tmp_path / ".claude" / "projects"
        proj_dir = projects_dir / "-Users-dev-test"
        proj_dir.mkdir(parents=True)
        shutil.copy(FIXTURES / "sample_session.jsonl", proj_dir / "s.jsonl")

        # Disable claude_code — should get no sessions
        sessions, raw, git_data = run_adapters(
            enabled_sources={
                "claude_code": False,
                "cursor": False,
                "codex": False,
                "git": False,
            },
        )
        assert len(sessions) == 0
        assert raw.get("claude_code") is None
        assert raw.get("cursor") is None
        assert raw.get("codex") is None
        assert git_data is None

    def test_enabled_source_scanned(self, tmp_path, monkeypatch):
        """When a source is enabled and detected, its adapter runs."""
        import nextmillionai.scanner as scanner_mod

        projects_dir = tmp_path / ".claude" / "projects"
        proj_dir = projects_dir / "-Users-dev-test"
        proj_dir.mkdir(parents=True)
        shutil.copy(FIXTURES / "sample_session.jsonl", proj_dir / "s.jsonl")
        monkeypatch.setattr(scanner_mod, "CLAUDE_PROJECTS_DIR", projects_dir)

        sessions, raw, git_data = run_adapters(
            enabled_sources={
                "claude_code": True,
                "cursor": False,
                "codex": False,
                "git": False,
            },
        )
        assert len(sessions) > 0
        assert raw["claude_code"] is not None


class TestProjectPathCollection:
    def test_project_paths_from_sessions(self, tmp_path, monkeypatch):
        """run_adapters should collect project paths from sessions."""
        import nextmillionai.scanner as scanner_mod

        projects_dir = tmp_path / ".claude" / "projects"
        proj_dir = projects_dir / "-Users-dev-test"
        proj_dir.mkdir(parents=True)
        shutil.copy(FIXTURES / "sample_session.jsonl", proj_dir / "s.jsonl")
        monkeypatch.setattr(scanner_mod, "CLAUDE_PROJECTS_DIR", projects_dir)

        sessions, raw, _ = run_adapters(
            enabled_sources={
                "claude_code": True,
                "cursor": False,
                "codex": False,
                "git": False,
            },
        )
        paths = {s.project_path for s in sessions}
        assert "/Users/dev/my-project" in paths
