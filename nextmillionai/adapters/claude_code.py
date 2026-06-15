"""
nextmillionai.adapters.claude_code -- Claude Code session adapter.

Reads JSONL session files from ``~/.claude/projects/`` and produces
a list of Session objects plus the legacy raw_data dict.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from nextmillionai.adapters._base import Session
from nextmillionai.scanner import (
    _FILE_TOOL_NAMES,
    _READ_TOOL_NAMES,
    _TERMINAL_TOOL_NAMES,
    _WRITE_TOOL_NAMES,
    CLAUDE_PROJECTS_DIR,
    safe_read_text,
    ts_to_iso,
)


def _log(msg: str) -> None:
    if os.environ.get("NEXTMILLIONAI_VERBOSE"):
        print(f"[scanner] {msg}", file=sys.stderr)


# Non-prompt user-role payloads injected by the Claude Code harness
_NON_PROMPT_PREFIXES = (
    "<command-name>",
    "<command-message>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<system-reminder>",
    "Caveat: The messages below",
)


def _scan_subagent_runs(session_dir: Path) -> dict:
    """Parse ``<session-id>/subagents/agent-*.jsonl`` transcripts.

    Newer Claude Code versions store each subagent run as its own JSONL
    beside the parent session. These are real measured agent work —
    skipping them silently undercounts both dispatches and runtime.
    Light parse: timestamps + message count per run; runtime capped at
    8h per run like every other duration in the pipeline.
    """
    out: dict = {"runs": 0, "minutes": 0.0, "messages": 0, "spans": []}
    sub_dir = session_dir / "subagents"
    if not sub_dir.is_dir():
        return out
    try:
        run_files = sorted(sub_dir.glob("agent-*.jsonl"))
    except OSError:
        return out
    # Agent runs use SPAN, not gap-splitting: an autonomous run is
    # continuous execution — a long stretch between transcript events is
    # the agent computing or waiting on a tool, never a human lunch
    # break. Gap-based active time models human idling and would
    # under-count real agent runtime.
    for rf in run_files:
        text = safe_read_text(rf)
        if not text:
            continue
        earliest = latest = None
        msgs = 0
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = obj.get("timestamp")
            if ts:
                iso = ts_to_iso(ts)
                if iso:
                    if earliest is None or iso < earliest:
                        earliest = iso
                    if latest is None or iso > latest:
                        latest = iso
            if obj.get("type") in ("user", "assistant"):
                msgs += 1
        if msgs == 0 and earliest is None:
            continue
        out["runs"] += 1
        out["messages"] += msgs
        if earliest and latest:
            try:
                a = datetime.fromisoformat(earliest.replace("Z", "+00:00"))
                b = datetime.fromisoformat(latest.replace("Z", "+00:00"))
                out["minutes"] += min(max((b - a).total_seconds() / 60.0, 0), 480)
                # Run spans are the HARD parallelism evidence: overlapping
                # agent transcripts = agents truly executing at once
                out["spans"].append([earliest, latest])
            except (ValueError, TypeError):
                pass
    return out


def _extract_prompt_text(obj: dict, message: dict) -> str:
    """Return the real human prompt text from a user-role JSONL line, or "".

    User-role lines also carry tool results, meta entries, slash-command
    wrappers, and harness-injected reminders — none of which are prompts the
    person typed, so counting them would fabricate prompt-volume signals.
    """
    if obj.get("isMeta"):
        return ""
    content = message.get("content")
    parts: list[str] = []
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        # A tool_result-only message is the harness replying, not the user
        if not parts:
            return ""
    text_parts = []
    for part in parts:
        stripped = part.strip()
        if not stripped or stripped.startswith(_NON_PROMPT_PREFIXES):
            continue
        text_parts.append(stripped)
    return "\n".join(text_parts)


class ClaudeCodeAdapter:
    """Adapter that scans Claude Code JSONL sessions."""

    def __init__(self, *, projects_dir: Path | None = None) -> None:
        self._projects_dir = projects_dir or CLAUDE_PROJECTS_DIR
        self._sessions: list[Session] = []
        self._raw: dict | None = None

    @property
    def name(self) -> str:
        return "claude_code"

    def detect(self) -> bool:
        return self._projects_dir.exists()

    def scan(self, project_filter: str | None = None) -> list[Session]:
        if not self.detect():
            _log("Claude Code: ~/.claude/projects/ not found, skipping")
            self._sessions = []
            self._raw = None
            return []

        _log("Claude Code: scanning projects...")
        project_dirs = sorted(self._projects_dir.iterdir())

        if project_filter:
            slug = project_filter.replace("/", "-").lstrip("-")
            project_dirs = [d for d in project_dirs if slug in d.name]

        sessions: list[Session] = []
        raw_sessions: list[dict] = []
        all_models: dict[str, int] = {}
        total_messages = 0
        total_tool_calls = 0
        earliest_ts: str | None = None
        latest_ts: str | None = None

        for proj_dir in project_dirs:
            if not proj_dir.is_dir() or proj_dir.name.startswith("."):
                continue

            jsonl_files = list(proj_dir.glob("*.jsonl"))
            if not jsonl_files:
                continue

            for jsonl_file in jsonl_files:
                session_id = jsonl_file.stem
                session_msgs = 0
                session_user_msgs = 0
                session_assistant_msgs = 0
                session_user_words = 0
                session_tool_calls = 0
                session_file_tool_calls = 0
                session_terminal_tool_calls = 0
                session_mcp_tool_calls = 0
                session_read_tool_calls = 0
                session_write_tool_calls = 0
                session_task_tool_calls = 0
                session_models: set[str] = set()
                session_earliest: str | None = None
                session_latest: str | None = None
                session_active_sec = 0.0
                _prev_dt = None
                git_branch: str | None = None
                version: str | None = None
                session_cwd: str | None = None
                prompt_word_counts: list[int] = []

                file_text = safe_read_text(jsonl_file)
                if not file_text:
                    continue

                for line in file_text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if session_cwd is None and obj.get("cwd"):
                        session_cwd = obj["cwd"]

                    msg_type = obj.get("type")
                    timestamp = obj.get("timestamp")

                    if timestamp:
                        ts_iso = ts_to_iso(timestamp)
                        if ts_iso:
                            if session_earliest is None or ts_iso < session_earliest:
                                session_earliest = ts_iso
                            if session_latest is None or ts_iso > session_latest:
                                session_latest = ts_iso
                            # Gap-based ACTIVE time: count stretches with
                            # <=30min between events; idle never counts
                            try:
                                _dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
                                if _prev_dt is not None:
                                    _gap = (_dt - _prev_dt).total_seconds()
                                    if 0 <= _gap <= 1800:
                                        session_active_sec += _gap
                                _prev_dt = _dt
                            except (ValueError, TypeError):
                                pass

                    if not git_branch and obj.get("gitBranch"):
                        git_branch = obj["gitBranch"]
                    if not version and obj.get("version"):
                        version = obj["version"]

                    if msg_type in ("user", "assistant"):
                        session_msgs += 1
                        total_messages += 1

                        message = obj.get("message", {})
                        model = message.get("model")
                        if model:
                            session_models.add(model)
                            all_models[model] = all_models.get(model, 0) + 1

                        if msg_type == "user":
                            # Only count real human prompts. User-role lines also
                            # carry tool results, meta entries, slash-command
                            # wrappers, and harness-injected reminders.
                            prompt_text = _extract_prompt_text(obj, message)
                            if prompt_text:
                                session_user_msgs += 1
                                wc = len(prompt_text.split())
                                session_user_words += wc
                                prompt_word_counts.append(wc)

                        if msg_type == "assistant":
                            session_assistant_msgs += 1
                            msg_content = message.get("content", [])
                            if isinstance(msg_content, list):
                                for block in msg_content:
                                    if isinstance(block, dict) and block.get("type") == "tool_use":
                                        session_tool_calls += 1
                                        total_tool_calls += 1
                                        tool_name = block.get("name", "")
                                        if tool_name in _TERMINAL_TOOL_NAMES:
                                            session_terminal_tool_calls += 1
                                        elif tool_name in _FILE_TOOL_NAMES:
                                            session_file_tool_calls += 1
                                        if tool_name.startswith("mcp__"):
                                            session_mcp_tool_calls += 1
                                        if tool_name == "Task":
                                            session_task_tool_calls += 1
                                        if tool_name in _READ_TOOL_NAMES:
                                            session_read_tool_calls += 1
                                        elif tool_name in _WRITE_TOOL_NAMES:
                                            session_write_tool_calls += 1

                proj_path = session_cwd or proj_dir.name

                # Subagent transcripts live in <session-id>/subagents/ —
                # each run file is direct dispatch evidence, its span is
                # agent runtime (kept separate from the user's own hours)
                sub = _scan_subagent_runs(proj_dir / session_id)
                if sub["runs"]:
                    session_task_tool_calls = max(session_task_tool_calls, sub["runs"])

                if session_msgs > 0:
                    # Parse timestamps for Session dataclass
                    started_at = None
                    ended_at = None
                    if session_earliest:
                        try:
                            started_at = datetime.fromisoformat(
                                session_earliest.replace("Z", "+00:00"),
                            )
                        except (ValueError, TypeError):
                            pass
                    if session_latest:
                        try:
                            ended_at = datetime.fromisoformat(
                                session_latest.replace("Z", "+00:00"),
                            )
                        except (ValueError, TypeError):
                            pass

                    tool_calls_by_type = {}
                    if session_file_tool_calls:
                        tool_calls_by_type["file"] = session_file_tool_calls
                    if session_terminal_tool_calls:
                        tool_calls_by_type["terminal"] = session_terminal_tool_calls
                    if session_mcp_tool_calls:
                        tool_calls_by_type["mcp"] = session_mcp_tool_calls
                    if session_read_tool_calls:
                        tool_calls_by_type["read"] = session_read_tool_calls
                    if session_write_tool_calls:
                        tool_calls_by_type["write"] = session_write_tool_calls
                    if session_task_tool_calls:
                        tool_calls_by_type["task"] = session_task_tool_calls

                    assistant_msgs = session_assistant_msgs

                    sessions.append(
                        Session(
                            tool="claude_code",
                            session_id=session_id,
                            project_path=proj_path,
                            started_at=started_at,
                            ended_at=ended_at,
                            user_msgs=session_user_msgs,
                            assistant_msgs=assistant_msgs,
                            tool_calls_by_type=tool_calls_by_type,
                            models=sorted(session_models),
                            prompt_word_counts=prompt_word_counts,
                            extras={
                                "git_branch": git_branch,
                                "version": version,
                                "total_tool_calls": session_tool_calls,
                                "subagentRuns": sub["runs"],
                                "agentMinutes": round(sub["minutes"], 1),
                                "agentRunSpans": sub["spans"],
                                "activeMinutes": round(session_active_sec / 60.0, 1),
                            },
                        )
                    )

                    raw_sessions.append(
                        {
                            "sessionId": session_id,
                            "project": proj_path,
                            "messages": session_msgs,
                            "userMessages": session_user_msgs,
                            "userWordCount": session_user_words,
                            "toolCalls": session_tool_calls,
                            "fileToolCalls": session_file_tool_calls,
                            "terminalToolCalls": session_terminal_tool_calls,
                            "mcpToolCalls": session_mcp_tool_calls,
                            "readToolCalls": session_read_tool_calls,
                            "writeToolCalls": session_write_tool_calls,
                            "models": sorted(session_models),
                            "gitBranch": git_branch,
                            "version": version,
                            "earliest": session_earliest,
                            "latest": session_latest,
                            "subagentRuns": sub["runs"],
                            "agentMinutes": round(sub["minutes"], 1),
                            "activeMinutes": round(session_active_sec / 60.0, 1),
                        }
                    )

                if session_earliest:
                    if earliest_ts is None or session_earliest < earliest_ts:
                        earliest_ts = session_earliest
                if session_latest:
                    if latest_ts is None or session_latest > latest_ts:
                        latest_ts = session_latest

        if not sessions:
            _log("Claude Code: no sessions found")
            self._sessions = []
            self._raw = None
            return []

        _log(
            f"Claude Code: {len(sessions)} sessions, {total_messages} messages, "
            f"{total_tool_calls} tool calls, {len(all_models)} models",
        )

        self._sessions = sessions
        self._raw = {
            "sessions": raw_sessions,
            "total_sessions": len(raw_sessions),
            "total_messages": total_messages,
            "models_used": all_models,
            "tool_calls": total_tool_calls,
            "subagent_runs": sum(s.get("subagentRuns", 0) for s in raw_sessions),
            "agent_hours": round(sum(s.get("agentMinutes", 0) for s in raw_sessions) / 60.0, 1),
            "earliest": earliest_ts,
            "latest": latest_ts,
        }

        return sessions

    def raw_data(self) -> dict | None:
        return self._raw
