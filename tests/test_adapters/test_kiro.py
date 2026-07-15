"""Tests for the Kiro CLI adapter."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nextmillionai.adapters.kiro import KiroAdapter


@pytest.fixture
def kiro_sessions_dir(tmp_path: Path) -> Path:
    """Create a synthetic Kiro sessions directory with test data."""
    sessions_dir = tmp_path / ".kiro" / "sessions" / "cli"
    sessions_dir.mkdir(parents=True)

    # Session 1: Normal session with tool usage
    session1_id = "aaaa1111-0000-0000-0000-000000000001"
    meta1 = {
        "session_id": session1_id,
        "cwd": "/Users/test/projects/myapp",
        "created_at": "2026-07-01T10:00:00.000000Z",
        "updated_at": "2026-07-01T10:45:00.000000Z",
        "title": "Fix the login bug in authentication service",
        "parent_session_id": None,
        "session_created_reason": "user",
        "session_state": {
            "version": "v1",
            "agent_name": "java-agent",
            "conversation_metadata": {},
            "rts_model_state": {},
            "permissions": {},
        },
    }
    (sessions_dir / f"{session1_id}.json").write_text(json.dumps(meta1))

    # JSONL transcript for session 1
    jsonl_lines = [
        json.dumps({
            "version": "v1",
            "kind": "Prompt",
            "data": {
                "message_id": "msg-001",
                "content": [{"kind": "text", "data": "Fix the login bug in the authentication service that causes timeout errors"}],
            },
        }),
        json.dumps({
            "version": "v1",
            "kind": "AssistantMessage",
            "data": {
                "message_id": "msg-002",
                "content": [
                    {"kind": "text", "data": ""},
                    {"kind": "toolUse", "data": {"toolUseId": "tu-001", "name": "read", "input": {}}},
                ],
            },
        }),
        json.dumps({
            "version": "v1",
            "kind": "ToolResults",
            "data": {
                "message_id": "msg-003",
                "content": [{"kind": "toolResult", "data": {"toolUseId": "tu-001", "content": []}}],
            },
        }),
        json.dumps({
            "version": "v1",
            "kind": "AssistantMessage",
            "data": {
                "message_id": "msg-004",
                "content": [
                    {"kind": "text", "data": ""},
                    {"kind": "toolUse", "data": {"toolUseId": "tu-002", "name": "shell", "input": {}}},
                ],
            },
        }),
        json.dumps({
            "version": "v1",
            "kind": "ToolResults",
            "data": {
                "message_id": "msg-005",
                "content": [{"kind": "toolResult", "data": {"toolUseId": "tu-002", "content": []}}],
            },
        }),
        json.dumps({
            "version": "v1",
            "kind": "AssistantMessage",
            "data": {
                "message_id": "msg-006",
                "content": [
                    {"kind": "text", "data": ""},
                    {"kind": "toolUse", "data": {"toolUseId": "tu-003", "name": "write", "input": {}}},
                ],
            },
        }),
        json.dumps({
            "version": "v1",
            "kind": "ToolResults",
            "data": {
                "message_id": "msg-007",
                "content": [{"kind": "toolResult", "data": {"toolUseId": "tu-003", "content": []}}],
            },
        }),
        json.dumps({
            "version": "v1",
            "kind": "Prompt",
            "data": {
                "message_id": "msg-008",
                "content": [{"kind": "text", "data": "Now run the tests to verify the fix works"}],
            },
        }),
        json.dumps({
            "version": "v1",
            "kind": "AssistantMessage",
            "data": {
                "message_id": "msg-009",
                "content": [
                    {"kind": "text", "data": ""},
                    {"kind": "toolUse", "data": {"toolUseId": "tu-004", "name": "shell", "input": {}}},
                ],
            },
        }),
    ]
    (sessions_dir / f"{session1_id}.jsonl").write_text("\n".join(jsonl_lines))

    # History file for session 1
    (sessions_dir / f"{session1_id}.history").write_text(
        "Fix the login bug in the authentication service that causes timeout errors\n"
        "Now run the tests to verify the fix works\n"
    )

    # Session 2: Subagent session
    session2_id = "aaaa1111-0000-0000-0000-000000000002"
    meta2 = {
        "session_id": session2_id,
        "cwd": "/Users/test/projects/myapp",
        "created_at": "2026-07-01T10:15:00.000000Z",
        "updated_at": "2026-07-01T10:20:00.000000Z",
        "title": "Search GitLab for related MRs",
        "parent_session_id": session1_id,
        "session_created_reason": "subagent",
        "session_state": {
            "version": "v1",
            "agent_name": None,
            "conversation_metadata": {},
            "rts_model_state": {},
            "permissions": {},
        },
    }
    (sessions_dir / f"{session2_id}.json").write_text(json.dumps(meta2))

    jsonl2 = [
        json.dumps({
            "version": "v1",
            "kind": "Prompt",
            "data": {"message_id": "msg-s01", "content": [{"kind": "text", "data": "Search for MRs"}]},
        }),
        json.dumps({
            "version": "v1",
            "kind": "AssistantMessage",
            "data": {
                "message_id": "msg-s02",
                "content": [
                    {"kind": "toolUse", "data": {"toolUseId": "tu-s01", "name": "get_merge_request", "input": {}}},
                ],
            },
        }),
    ]
    (sessions_dir / f"{session2_id}.jsonl").write_text("\n".join(jsonl2))

    # Session 3: Empty session (no messages — should be excluded)
    session3_id = "aaaa1111-0000-0000-0000-000000000003"
    meta3 = {
        "session_id": session3_id,
        "cwd": "/Users/test/projects/other",
        "created_at": "2026-07-02T09:00:00.000000Z",
        "updated_at": "2026-07-02T09:00:01.000000Z",
        "title": "",
        "parent_session_id": None,
        "session_created_reason": "user",
        "session_state": {"version": "v1"},
    }
    (sessions_dir / f"{session3_id}.json").write_text(json.dumps(meta3))
    (sessions_dir / f"{session3_id}.jsonl").write_text("")

    return sessions_dir


class TestKiroAdapterDetect:
    def test_detect_true(self, kiro_sessions_dir: Path) -> None:
        adapter = KiroAdapter(sessions_dir=kiro_sessions_dir)
        assert adapter.detect() is True

    def test_detect_false(self, tmp_path: Path) -> None:
        adapter = KiroAdapter(sessions_dir=tmp_path / "nonexistent")
        assert adapter.detect() is False

    def test_name(self) -> None:
        adapter = KiroAdapter()
        assert adapter.name == "kiro"


class TestKiroAdapterScan:
    def test_scan_produces_sessions(self, kiro_sessions_dir: Path) -> None:
        adapter = KiroAdapter(sessions_dir=kiro_sessions_dir)
        sessions = adapter.scan()
        # Session 3 is empty → excluded. Sessions 1 and 2 have messages.
        assert len(sessions) == 2

    def test_session_metadata(self, kiro_sessions_dir: Path) -> None:
        adapter = KiroAdapter(sessions_dir=kiro_sessions_dir)
        sessions = adapter.scan()
        s1 = next(s for s in sessions if "000000000001" in s.session_id)

        assert s1.tool == "kiro"
        assert s1.project_path == "/Users/test/projects/myapp"
        assert s1.started_at == datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc)
        assert s1.ended_at == datetime(2026, 7, 1, 10, 45, 0, tzinfo=timezone.utc)

    def test_message_counts(self, kiro_sessions_dir: Path) -> None:
        adapter = KiroAdapter(sessions_dir=kiro_sessions_dir)
        sessions = adapter.scan()
        s1 = next(s for s in sessions if "000000000001" in s.session_id)

        assert s1.user_msgs == 2
        assert s1.assistant_msgs == 4

    def test_tool_calls_extracted(self, kiro_sessions_dir: Path) -> None:
        adapter = KiroAdapter(sessions_dir=kiro_sessions_dir)
        sessions = adapter.scan()
        s1 = next(s for s in sessions if "000000000001" in s.session_id)

        assert s1.tool_calls_by_type == {"read": 1, "shell": 2, "write": 1}

    def test_prompt_word_counts(self, kiro_sessions_dir: Path) -> None:
        adapter = KiroAdapter(sessions_dir=kiro_sessions_dir)
        sessions = adapter.scan()
        s1 = next(s for s in sessions if "000000000001" in s.session_id)

        # Two prompts with known word counts
        assert len(s1.prompt_word_counts) == 2
        assert s1.prompt_word_counts[0] == 12  # "Fix the login bug..."
        assert s1.prompt_word_counts[1] == 9   # "Now run the tests..."

    def test_subagent_detected(self, kiro_sessions_dir: Path) -> None:
        adapter = KiroAdapter(sessions_dir=kiro_sessions_dir)
        sessions = adapter.scan()
        s2 = next(s for s in sessions if "000000000002" in s.session_id)

        assert s2.extras["is_subagent"] is True
        assert s2.extras["parent_session_id"] == "aaaa1111-0000-0000-0000-000000000001"

    def test_agent_name_extracted(self, kiro_sessions_dir: Path) -> None:
        adapter = KiroAdapter(sessions_dir=kiro_sessions_dir)
        sessions = adapter.scan()
        s1 = next(s for s in sessions if "000000000001" in s.session_id)

        assert s1.extras["agent_name"] == "java-agent"

    def test_empty_session_excluded(self, kiro_sessions_dir: Path) -> None:
        adapter = KiroAdapter(sessions_dir=kiro_sessions_dir)
        sessions = adapter.scan()
        ids = [s.session_id for s in sessions]
        assert "aaaa1111-0000-0000-0000-000000000003" not in ids

    def test_project_filter(self, kiro_sessions_dir: Path) -> None:
        adapter = KiroAdapter(sessions_dir=kiro_sessions_dir)
        sessions = adapter.scan(project_filter="myapp")
        # Only sessions with "myapp" in cwd
        assert all("myapp" in (s.project_path or "") for s in sessions)


class TestKiroAdapterRawData:
    def test_raw_data_after_scan(self, kiro_sessions_dir: Path) -> None:
        adapter = KiroAdapter(sessions_dir=kiro_sessions_dir)
        adapter.scan()
        raw = adapter.raw_data()

        assert raw is not None
        assert raw["total_sessions"] == 3  # 3 json files exist
        assert raw["parsed_sessions"] == 2  # only 2 had messages
        assert raw["subagent_sessions"] == 1
        assert raw["total_user_msgs"] == 3  # 2 from s1, 1 from s2
        assert raw["total_assistant_msgs"] == 5  # 4 from s1, 1 from s2
        assert raw["total_tool_calls"] == 5  # read+2*shell+write from s1, get_merge_request from s2

    def test_raw_data_none_before_scan(self) -> None:
        adapter = KiroAdapter(sessions_dir=Path("/nonexistent"))
        assert adapter.raw_data() is None

    def test_raw_data_has_timestamps(self, kiro_sessions_dir: Path) -> None:
        adapter = KiroAdapter(sessions_dir=kiro_sessions_dir)
        adapter.scan()
        raw = adapter.raw_data()

        assert raw["earliest"] is not None
        assert raw["latest"] is not None
        assert "2026-07-01" in raw["earliest"]


class TestKiroAdapterNoDir:
    def test_scan_missing_dir(self, tmp_path: Path) -> None:
        adapter = KiroAdapter(sessions_dir=tmp_path / "does_not_exist")
        sessions = adapter.scan()
        assert sessions == []
        assert adapter.raw_data() is None
