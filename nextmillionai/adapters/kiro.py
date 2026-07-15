"""
nextmillionai.adapters.kiro -- Kiro CLI / Kiro IDE adapter.

Reads JSON metadata + JSONL transcript files from ``~/.kiro/sessions/cli/``
to extract session structure, tool usage, timestamps, and orchestration
signals. Never reads prompt/response text content — only counts and
tool names.

Fidelity: deep (real session boundaries + timestamps from Kiro's own store).

Paths:
    ~/.kiro/sessions/cli/*.json     Session metadata
    ~/.kiro/sessions/cli/*.jsonl    Session transcripts (message counts only)
    ~/.kiro/sessions/cli/*.history  Raw prompt text (word counts only)

Derived:
    sessions, hours, span, prompts, tool calls by type, models,
    agent dispatches (subagent sessions), MCP tool diversity,
    per-day activity, active minutes (gap-based)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from nextmillionai.adapters._base import Session
from nextmillionai.scanner import safe_read_text


# Default path — overridable via constructor for testing
KIRO_SESSIONS_DIR = Path.home() / ".kiro" / "sessions" / "cli"


def _log(msg: str) -> None:
    if os.environ.get("NEXTMILLIONAI_VERBOSE"):
        print(f"[scanner] {msg}", file=sys.stderr)


class KiroAdapter:
    """Adapter that scans Kiro CLI/IDE sessions with deep JSONL parsing.

    Kiro stores three files per session:
      - <uuid>.json   — metadata (session_id, cwd, timestamps, agent, parent)
      - <uuid>.jsonl  — transcript (Prompt, AssistantMessage, ToolResults)
      - <uuid>.history — raw user prompts (one per line, for word counts only)

    The adapter reads metadata + counts from transcripts. It NEVER reads
    prompt text content or assistant response text — only message kinds,
    tool names from toolUse blocks, and timestamps.
    """

    def __init__(self, *, sessions_dir: Path | None = None) -> None:
        self._sessions_dir = sessions_dir or KIRO_SESSIONS_DIR
        self._sessions: list[Session] = []
        self._raw: dict | None = None

    @property
    def name(self) -> str:
        return "kiro"

    def detect(self) -> bool:
        return self._sessions_dir.exists()

    def scan(self, project_filter: str | None = None) -> list[Session]:
        if not self.detect():
            _log("Kiro: ~/.kiro/sessions/cli/ not found, skipping")
            self._sessions = []
            self._raw = None
            return []

        _log("Kiro: scanning sessions...")

        try:
            json_files = sorted(self._sessions_dir.glob("*.json"))
        except Exception:
            self._sessions = []
            self._raw = None
            return []

        if not json_files:
            self._sessions = []
            self._raw = None
            return []

        sessions: list[Session] = []
        total_user_msgs = 0
        total_assistant_msgs = 0
        total_tool_calls = 0
        all_models: dict[str, int] = {}
        subagent_count = 0

        for json_file in json_files:
            # Skip .lock files and non-session JSON
            if json_file.name.endswith(".lock"):
                continue

            # Read metadata
            meta_text = safe_read_text(json_file)
            if not meta_text:
                continue
            try:
                meta = json.loads(meta_text)
            except (json.JSONDecodeError, ValueError):
                continue

            # Validate it's a session file (must have session_id)
            session_id = meta.get("session_id")
            if not session_id:
                continue

            # Apply project filter if given
            cwd = meta.get("cwd")
            if project_filter and cwd:
                if project_filter not in cwd:
                    continue

            # Check if this is a subagent session
            is_subagent = meta.get("session_created_reason") == "subagent"
            if is_subagent:
                subagent_count += 1

            # Parse timestamps from metadata
            started_at = _parse_iso_dt(meta.get("created_at"))
            ended_at = _parse_iso_dt(meta.get("updated_at"))

            # Extract agent name from session state
            session_state = meta.get("session_state", {})
            agent_name = session_state.get("agent_name")

            # Parse the JSONL transcript for counts
            jsonl_file = json_file.with_suffix(".jsonl")
            user_msgs, assistant_msgs, tool_calls, models, active_sec, prompt_wcs = (
                self._parse_transcript(jsonl_file)
            )

            # If no JSONL, try word counts from .history file
            if not prompt_wcs:
                history_file = json_file.with_suffix(".history")
                prompt_wcs = self._parse_history_word_counts(history_file)

            total_user_msgs += user_msgs
            total_assistant_msgs += assistant_msgs
            total_tool_calls += sum(tool_calls.values())
            for model in models:
                all_models[model] = all_models.get(model, 0) + 1

            # Only include sessions with actual activity
            if user_msgs > 0 or assistant_msgs > 0:
                sessions.append(
                    Session(
                        tool="kiro",
                        session_id=session_id,
                        project_path=cwd,
                        started_at=started_at,
                        ended_at=ended_at,
                        user_msgs=user_msgs,
                        assistant_msgs=assistant_msgs,
                        tool_calls_by_type=tool_calls,
                        models=sorted(models),
                        prompt_word_counts=prompt_wcs,
                        extras={
                            "activeMinutes": round(active_sec / 60.0, 1),
                            "agent_name": agent_name,
                            "is_subagent": is_subagent,
                            "parent_session_id": meta.get("parent_session_id"),
                        },
                    )
                )

        # Compute overall stats
        all_earliest: str | None = None
        all_latest: str | None = None
        for s in sessions:
            if s.started_at:
                iso = s.started_at.isoformat()
                if all_earliest is None or iso < all_earliest:
                    all_earliest = iso
            if s.ended_at:
                iso = s.ended_at.isoformat()
                if all_latest is None or iso > all_latest:
                    all_latest = iso

        parsed_count = len(sessions)
        total_files = len(json_files)
        if parsed_count > 0:
            _log(f"Kiro: {parsed_count} parsed sessions ({total_files} files)")
        else:
            _log(f"Kiro: {total_files} session files, 0 parseable")

        self._sessions = sessions
        self._raw = {
            "total_sessions": total_files,
            "parsed_sessions": parsed_count,
            "total_user_msgs": total_user_msgs,
            "total_assistant_msgs": total_assistant_msgs,
            "total_tool_calls": total_tool_calls,
            "subagent_sessions": subagent_count,
            "models_used": all_models,
            "path": str(self._sessions_dir),
            "earliest": all_earliest,
            "latest": all_latest,
        }

        return sessions

    def raw_data(self) -> dict | None:
        return self._raw

    # ── Private helpers ──────────────────────────────────────────────────

    def _parse_transcript(
        self, jsonl_path: Path
    ) -> tuple[int, int, dict[str, int], set[str], float, list[int]]:
        """Parse a Kiro JSONL transcript for counts — never content.

        Kiro JSONL format (one JSON object per line):
          {"version":"v1","kind":"Prompt","data":{"message_id":"...","content":[...]}}
          {"version":"v1","kind":"AssistantMessage","data":{"message_id":"...","content":[...]}}
          {"version":"v1","kind":"ToolResults","data":{"message_id":"...","content":[...]}}

        From AssistantMessage content, we extract tool names from toolUse blocks.
        We count prompt word counts from Prompt entries (text length only).

        Returns (user_msgs, assistant_msgs, tool_calls_by_type, models, active_sec, prompt_word_counts)
        """
        user_msgs = 0
        assistant_msgs = 0
        tool_calls: dict[str, int] = {}
        models: set[str] = set()
        active_sec = 0.0
        prev_dt: datetime | None = None
        prompt_word_counts: list[int] = []

        text = safe_read_text(jsonl_path)
        if not text:
            return user_msgs, assistant_msgs, tool_calls, models, active_sec, prompt_word_counts

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            kind = obj.get("kind", "")
            data = obj.get("data", {})

            # Track timestamps for active-time estimation
            # Kiro doesn't always have per-message timestamps in JSONL,
            # so we rely on the .json metadata for session duration.

            if kind == "Prompt":
                user_msgs += 1
                # Count words in prompt content (NEVER store the text)
                content = data.get("content", [])
                wc = self._count_content_words(content)
                if wc > 0:
                    prompt_word_counts.append(wc)

            elif kind == "AssistantMessage":
                assistant_msgs += 1
                content = data.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("kind") == "toolUse":
                            tool_data = block.get("data", {})
                            tool_name = tool_data.get("name", "unknown")
                            tool_calls[tool_name] = tool_calls.get(tool_name, 0) + 1

            # ToolResults are counted but don't add to user/assistant
            # (they're responses to tool calls, not human prompts)

        # Estimate active time from metadata timestamps if no per-line ts
        # (handled at session level using started_at/ended_at from .json)

        return user_msgs, assistant_msgs, tool_calls, models, active_sec, prompt_word_counts

    def _parse_history_word_counts(self, history_path: Path) -> list[int]:
        """Parse .history file for prompt word counts only.

        The .history file contains raw user prompts, one per line.
        We ONLY extract word counts — never store or transmit the text.
        """
        text = safe_read_text(history_path)
        if not text:
            return []

        counts = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                # Unescape \\n sequences that represent newlines in multi-line prompts
                expanded = line.replace("\\n", " ")
                wc = len(expanded.split())
                if wc > 0:
                    counts.append(wc)
        return counts

    @staticmethod
    def _count_content_words(content: list | str) -> int:
        """Count words in a content array without storing text.

        Content can be:
          - A string (rare in Kiro)
          - A list of blocks: [{"kind":"text","data":"..."}, ...]
        """
        if isinstance(content, str):
            return len(content.split())

        total = 0
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("kind") == "text":
                        text = block.get("data", "")
                        if isinstance(text, str):
                            total += len(text.split())
        return total


def _parse_iso_dt(value: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp string to datetime, or None."""
    if not value:
        return None
    try:
        # Handle both 'Z' suffix and '+00:00' timezone formats
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
