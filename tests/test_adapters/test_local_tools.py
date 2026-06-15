"""Tests for the wider-field adapters (Aider/Cline/Continue/Copilot/
Windsurf/Zed/JetBrains/Cody), local model runtimes, and user-registered
custom adapters.

Every adapter is exercised three ways: real synthetic data, absent
(detect() False, no crash), and present-but-empty (detected, zero
sessions, honest counts). Fidelity must ride along in raw_data."""

import json
from pathlib import Path

from nextmillionai.adapters.local_models import detect_local_models
from nextmillionai.adapters.local_tools import (
    AiderAdapter,
    AntigravityAdapter,
    ClineAdapter,
    CodyAdapter,
    ContinueAdapter,
    CopilotChatAdapter,
    CustomLogAdapter,
    JetBrainsAIAdapter,
    WindsurfAdapter,
    ZedAdapter,
    get_local_tool_adapters,
    load_custom_adapters,
)


def _vscode_user(home: Path) -> Path:
    d = home / "Library" / "Application Support" / "Code" / "User"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Absent data: every adapter detects False and scans clean ────────────────


def test_all_adapters_absent_home(tmp_path):
    for adapter in get_local_tool_adapters(home=tmp_path):
        assert adapter.detect() is False, adapter.name
        assert adapter.scan() == []
        assert adapter.raw_data() is None


# ── Aider ────────────────────────────────────────────────────────────────────


def test_aider_parses_session_markers(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path / "nma"))
    (tmp_path / ".aider.chat.history.md").write_text(
        "# aider chat started at 2026-06-01 10:00:00\n\n"
        "#### make the tests pass\n\nok done\n\n"
        "#### now refactor\n\nsure\n\n"
        "# aider chat started at 2026-06-02 09:30:00\n\n"
        "#### add a feature\n\nbuilt\n"
    )
    a = AiderAdapter(home=tmp_path)
    assert a.detect() is True
    sessions = a.scan()
    assert len(sessions) == 2
    assert sessions[0].user_msgs == 2
    assert sessions[0].started_at.isoformat().startswith("2026-06-01T10:00")
    assert sessions[1].user_msgs == 1
    assert a.raw_data()["fidelity"] == "deep"


def test_aider_present_but_empty(tmp_path):
    (tmp_path / ".aider").mkdir()  # installed, no history anywhere
    a = AiderAdapter(home=tmp_path)
    assert a.detect() is True
    assert a.scan() == []
    assert a.raw_data()["historyFiles"] == 0


# ── Cline ────────────────────────────────────────────────────────────────────


def test_cline_tasks(tmp_path):
    tasks = _vscode_user(tmp_path) / "globalStorage" / "saoudrizwan.claude-dev" / "tasks"
    t1 = tasks / "1750000000000"
    t1.mkdir(parents=True)
    (t1 / "api_conversation_history.json").write_text(
        json.dumps(
            [
                {"role": "user", "content": "do x"},
                {"role": "assistant", "content": "done"},
                {"role": "user", "content": "do y"},
            ]
        )
    )
    a = ClineAdapter(home=tmp_path)
    assert a.detect() is True
    sessions = a.scan()
    assert len(sessions) == 1
    assert sessions[0].user_msgs == 2
    assert sessions[0].assistant_msgs == 1
    assert sessions[0].started_at is not None
    assert a.raw_data()["fidelity"] == "deep"


# ── Continue.dev ─────────────────────────────────────────────────────────────


def test_continue_sessions(tmp_path):
    sdir = tmp_path / ".continue" / "sessions"
    sdir.mkdir(parents=True)
    (sdir / "sessions.json").write_text(
        json.dumps(
            [
                {
                    "sessionId": "abc",
                    "dateCreated": 1750000000000,
                    "workspaceDirectory": "/proj/x",
                }
            ]
        )
    )
    (sdir / "abc.json").write_text(
        json.dumps(
            {
                "sessionId": "abc",
                "history": [
                    {"message": {"role": "user", "content": "hi"}},
                    {
                        "message": {"role": "assistant", "content": "yo"},
                        "completionOptions": {"model": "claude-sonnet-4-6"},
                    },
                ],
            }
        )
    )
    a = ContinueAdapter(home=tmp_path)
    assert a.detect() is True
    sessions = a.scan()
    assert len(sessions) == 1
    assert sessions[0].user_msgs == 1
    assert sessions[0].project_path == "/proj/x"
    assert sessions[0].models == ["claude-sonnet-4-6"]


def test_continue_present_but_empty(tmp_path):
    (tmp_path / ".continue" / "sessions").mkdir(parents=True)
    a = ContinueAdapter(home=tmp_path)
    assert a.detect() is True
    assert a.scan() == []
    assert a.raw_data()["sessions"] == 0


# ── Copilot Chat ─────────────────────────────────────────────────────────────


def test_copilot_chat_sessions(tmp_path):
    cs = _vscode_user(tmp_path) / "workspaceStorage" / "ws1" / "chatSessions"
    cs.mkdir(parents=True)
    (cs / "chat1.json").write_text(
        json.dumps(
            {
                "creationDate": 1750000000000,
                "requests": [{"message": "q1"}, {"message": "q2"}],
            }
        )
    )
    a = CopilotChatAdapter(home=tmp_path)
    assert a.detect() is True
    sessions = a.scan()
    assert len(sessions) == 1
    assert sessions[0].user_msgs == 2


# ── Windsurf (counts — never invented sessions) ─────────────────────────────


def test_windsurf_counts_only(tmp_path):
    cascade = tmp_path / ".codeium" / "windsurf" / "cascade"
    cascade.mkdir(parents=True)
    (cascade / "blob1.pb").write_bytes(b"\x00\x01binary")
    a = WindsurfAdapter(home=tmp_path)
    assert a.detect() is True
    assert a.scan() == []  # no sessions — store is not honestly parseable
    raw = a.raw_data()
    assert raw["fidelity"] == "counts"
    assert raw["files"] == 1
    assert "insufficient" in raw["note"]


# ── Zed AI ───────────────────────────────────────────────────────────────────


def test_zed_conversations(tmp_path):
    conv = tmp_path / "Library" / "Application Support" / "Zed" / "conversations"
    conv.mkdir(parents=True)
    (conv / "c1.json").write_text(
        json.dumps(
            {
                "messages": [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "hi"},
                ]
            }
        )
    )
    a = ZedAdapter(home=tmp_path)
    assert a.detect() is True
    sessions = a.scan()
    assert len(sessions) == 1
    assert sessions[0].user_msgs == 1


# ── JetBrains AI (presence only) ─────────────────────────────────────────────


def test_jetbrains_presence_only(tmp_path):
    opts = tmp_path / "Library" / "Application Support" / "JetBrains" / "IntelliJIdea2026.1"
    (opts / "options").mkdir(parents=True)
    (opts / "options" / "AIAssistant.xml").write_text("<application/>")
    a = JetBrainsAIAdapter(home=tmp_path)
    assert a.detect() is True
    assert a.scan() == []
    raw = a.raw_data()
    assert raw["fidelity"] == "presence"
    assert "IntelliJIdea2026.1" in raw["ides"]
    assert "insufficient" in raw["note"]


# ── Cody (counts) ────────────────────────────────────────────────────────────


def test_cody_counts(tmp_path):
    d = _vscode_user(tmp_path) / "globalStorage" / "sourcegraph.cody-ai"
    d.mkdir(parents=True)
    (d / "history.json").write_text("{}")
    a = CodyAdapter(home=tmp_path)
    assert a.detect() is True
    assert a.scan() == []
    assert a.raw_data()["storageFiles"] == 1
    assert a.raw_data()["fidelity"] == "counts"


# ── Antigravity (counts — Protobuf trajectories, never invented) ────────────


def test_antigravity_counts_conversations(tmp_path):
    conv = tmp_path / ".gemini" / "antigravity" / "conversations"
    conv.mkdir(parents=True)
    (conv / "t1.pb").write_bytes(b"\x0a\x05hello")
    (conv / "t2.pb").write_bytes(b"\x0a\x05world")
    brain = tmp_path / ".gemini" / "antigravity" / "brain" / "task-1"
    brain.mkdir(parents=True)
    (brain / "task.md").write_text("# build the thing")

    a = AntigravityAdapter(home=tmp_path)
    assert a.detect() is True
    assert a.scan() == []  # trajectories are protobuf — never invented as sessions
    raw = a.raw_data()
    assert raw["fidelity"] == "counts"
    assert raw["conversations"] == 2
    assert raw["brainTasks"] == 1
    assert "insufficient" in raw["note"]


def test_antigravity_detects_vscode_state_dir(tmp_path):
    # No ~/.gemini data, but the IDE's globalStorage marks the install.
    gs = tmp_path / "Library" / "Application Support" / "Antigravity IDE" / "User" / "globalStorage"
    gs.mkdir(parents=True)
    (gs / "state.vscdb").write_bytes(b"SQLite format 3\x00")

    a = AntigravityAdapter(home=tmp_path)
    assert a.detect() is True
    assert a.scan() == []
    assert a.raw_data()["conversations"] == 0


# ── Custom adapters (nextmillionai.config.json) ──────────────────────────────


def test_custom_adapter_file_per_session(tmp_path):
    logs = tmp_path / "mytool-logs"
    logs.mkdir()
    (logs / "s1.jsonl").write_text('{"x":1}\n')
    (logs / "s2.jsonl").write_text('{"x":2}\n')
    spec = {
        "id": "mytool",
        "label": "My Tool",
        "path": str(logs),
        "glob": "*.jsonl",
        "format": "file-per-session",
    }
    a = CustomLogAdapter(spec, home=tmp_path)
    assert a.name == "mytool"
    assert a.detect() is True
    sessions = a.scan()
    assert len(sessions) == 2
    assert all(s.extras.get("timestampFidelity") == "mtime" for s in sessions)
    assert a.raw_data()["custom"] is True


def test_custom_adapter_loaded_from_config(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "a.txt").write_text("x")
    nma_home = tmp_path / "nma-home"
    nma_home.mkdir()
    (nma_home / "nextmillionai.config.json").write_text(
        json.dumps(
            {
                "adapters": [
                    {"id": "diyharness", "label": "DIY", "path": str(logs), "glob": "*.txt"},
                    {"id": "claude_code", "path": str(logs)},  # reserved → skipped
                    {"id": "nopath"},  # invalid → skipped
                ]
            }
        )
    )
    monkeypatch.setenv("NEXTMILLIONAI_HOME", str(nma_home))
    monkeypatch.chdir(tmp_path)  # no cwd config
    adapters = load_custom_adapters(home=tmp_path)
    assert [a.name for a in adapters] == ["diyharness"]
    assert adapters[0].scan()[0].tool == "diyharness"


# ── Local model runtimes ─────────────────────────────────────────────────────


def test_ollama_detection(tmp_path):
    man = tmp_path / ".ollama" / "models" / "manifests" / "registry.ollama.ai" / "library"
    (man / "llama3").mkdir(parents=True)
    (man / "llama3" / "latest").write_text("{}")
    (tmp_path / ".ollama" / "history").write_text("prompt one\nprompt two\n")

    result = detect_local_models(home=tmp_path)
    assert result is not None
    ollama = [r for r in result["runtimes"] if r["runtime"] == "ollama"][0]
    assert "llama3:latest" in ollama["models"]
    assert ollama["promptHistoryLines"] == 2
    assert result["fidelity"] == "counts"


def test_lmstudio_detection(tmp_path):
    conv = tmp_path / ".lmstudio" / "conversations"
    conv.mkdir(parents=True)
    (conv / "c1.json").write_text("{}")
    (tmp_path / ".lmstudio" / "models" / "meta" / "llama-3-8b").mkdir(parents=True)

    result = detect_local_models(home=tmp_path)
    lms = [r for r in result["runtimes"] if r["runtime"] == "lmstudio"][0]
    assert lms["conversations"] == 1
    assert "llama-3-8b" in lms["models"]


def test_no_local_models(tmp_path):
    assert detect_local_models(home=tmp_path) is None


# ── Mixed toolchain through the registry consent group ──────────────────────


def test_registry_consent_group_gates_other_tools(tmp_path, monkeypatch):
    """other_tools=False keeps every wider-field adapter out of the run."""
    import nextmillionai.adapters._registry as registry
    from nextmillionai.adapters._registry import run_adapters

    conv = tmp_path / ".continue" / "sessions"
    conv.mkdir(parents=True)
    monkeypatch.setattr(registry, "get_session_adapters", lambda: [ContinueAdapter(home=tmp_path)])

    _, raw, _ = run_adapters(
        enabled_sources={"other_tools": False, "git": False},
    )
    assert raw["continue"] is None

    _, raw, _ = run_adapters(
        enabled_sources={"other_tools": True, "git": False},
    )
    assert raw["continue"] is not None


# ── Fork-hosted extensions (Cursor/Windsurf run Cline + Cody too) ───────────


def test_cline_inside_cursor_fork(tmp_path):
    """Cline tasks under Cursor's globalStorage must be found — scanning
    only vanilla VS Code misses every fork-hosted install."""
    tasks = (
        tmp_path
        / "Library"
        / "Application Support"
        / "Cursor"
        / "User"
        / "globalStorage"
        / "saoudrizwan.claude-dev"
        / "tasks"
        / "1750000000000"
    )
    tasks.mkdir(parents=True)
    (tasks / "api_conversation_history.json").write_text(
        json.dumps([{"role": "user", "content": "go"}])
    )
    a = ClineAdapter(home=tmp_path)
    assert a.detect() is True
    assert len(a.scan()) == 1


def test_copilot_never_reads_fork_chats(tmp_path):
    """A fork's chatSessions belong to the fork — Copilot must not count
    Cursor/Windsurf chats as its own."""
    cs = (
        tmp_path
        / "Library"
        / "Application Support"
        / "Cursor"
        / "User"
        / "workspaceStorage"
        / "ws1"
        / "chatSessions"
    )
    cs.mkdir(parents=True)
    (cs / "chat1.json").write_text(json.dumps({"requests": [{"message": "q"}]}))
    a = CopilotChatAdapter(home=tmp_path)
    assert a.detect() is False
    assert a.scan() == []
