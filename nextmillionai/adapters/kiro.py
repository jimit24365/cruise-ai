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
    sessions, hours, span, prompts, tool calls by type,
    agent dispatches (subagent sessions), MCP tool diversity,
    per-day activity
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from nextmillionai.adapters._base import Session
from nextmillionai.scanner import safe_read_text


def _log(msg: str) -> None:
    if os.environ.get("NEXTMILLIONAI_VERBOSE"):
        print(f"[scanner] {msg}", file=sys.stderr)


# Kiro's builtin (non-MCP) tool names. Anything else in a CLI transcript's
# toolUse blocks is an MCP-provided tool (jira, confluence, gitlab, ...) —
# declared per session via extras["mcpToolCalls"] so the aggregator's fold
# never needs kiro-specific knowledge.
KIRO_BUILTIN_TOOLS = frozenset(
    {
        "shell",
        "read",
        "write",
        "edit",
        "fs_read",
        "fs_write",
        "execute_bash",
        "use_aws",
        "report_issue",
        "thinking",
        "todo_list",
        "knowledge",
        "introspect",
        "delegate",
        "grep",
        "glob",
    }
)


class KiroAdapter:
    """Adapter that scans Kiro CLI and IDE sessions.

    **Generation 1 — Kiro CLI** (deep fidelity):
      Path: ``~/.kiro/sessions/cli/``
      Files: ``<uuid>.json`` + ``<uuid>.jsonl`` + ``<uuid>.history``
      Reads: metadata, message counts, tool names from toolUse blocks, timestamps.

    **Generation 2 — Kiro IDE** (deep fidelity, no tool-call names):
      Path: ``~/Library/Application Support/Kiro/User/globalStorage/kiro.kiroagent/``
      Files: ``sessions/sessions.json`` (index) + ``sessions/<uuid>.json`` (session data)
             ``workspace-sessions/<b64-path>/sessions.json`` + ``<uuid>.json``
      Reads: session metadata, history[] message counts, prompt word counts,
             model names from promptLogs, autonomyMode, sessionType.

    Both generations are scanned and deduped by session_id. The adapter
    NEVER reads prompt text content or assistant response text — only
    counts, tool names (CLI only), and timestamps.
    """

    def __init__(
        self,
        *,
        sessions_dir: Path | None = None,
        ide_dirs: list[Path] | None = None,
    ) -> None:
        # Late-bind the scanner path constants so test monkeypatching of
        # nextmillionai.scanner.KIRO_* propagates even to bare KiroAdapter().
        import nextmillionai.scanner as scanner_mod

        self._sessions_dir = sessions_dir or scanner_mod.KIRO_SESSIONS_DIR
        self._ide_dirs = ide_dirs if ide_dirs is not None else scanner_mod.KIRO_IDE_DIRS
        self._sessions: list[Session] = []
        self._raw: dict | None = None

    @property
    def name(self) -> str:
        return "kiro"

    def detect(self) -> bool:
        if self._sessions_dir.exists():
            return True
        return any(d.exists() for d in self._ide_dirs)

    def scan(self, project_filter: str | None = None) -> list[Session]:
        if not self.detect():
            _log("Kiro: no CLI or IDE sessions found, skipping")
            self._sessions = []
            self._raw = None
            return []

        _log("Kiro: scanning sessions...")

        cli_sessions = self._scan_cli(project_filter)
        seen_ids = {s.session_id for s in cli_sessions}
        ide_sessions = self._scan_ide(project_filter, seen_ids)

        sessions = cli_sessions + ide_sessions

        # ── Compute overall stats ────────────────────────────────────────────
        total_user_msgs = sum(s.user_msgs for s in sessions)
        total_assistant_msgs = sum(s.assistant_msgs for s in sessions)
        total_tool_calls = sum(sum(s.tool_calls_by_type.values()) for s in sessions)
        subagent_count = sum(1 for s in sessions if s.extras.get("is_subagent"))
        all_models: dict[str, int] = {}
        for s in sessions:
            for model in s.models:
                all_models[model] = all_models.get(model, 0) + 1

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
        ide_count = len(ide_sessions)
        if parsed_count > 0:
            _log(f"Kiro: {parsed_count} total sessions (CLI + IDE)")
        else:
            _log("Kiro: 0 parseable sessions")

        self._sessions = sessions
        self._raw = {
            "label": "Kiro",
            "fidelity": "deep",
            "total_sessions": parsed_count,
            "parsed_sessions": parsed_count,
            "cli_sessions": len(cli_sessions),
            "ide_sessions": ide_count,
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

    def _scan_cli(self, project_filter: str | None = None) -> list[Session]:
        """Scan Kiro CLI sessions from ~/.kiro/sessions/cli/."""
        json_files: list[Path] = []
        if self._sessions_dir.exists():
            try:
                json_files = sorted(self._sessions_dir.glob("*.json"))
            except Exception:
                pass

        sessions: list[Session] = []

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

            # Parse timestamps from metadata
            started_at = _parse_iso_dt(meta.get("created_at"))
            ended_at = _parse_iso_dt(meta.get("updated_at"))

            # Extract agent name from session state
            session_state = meta.get("session_state", {})
            agent_name = session_state.get("agent_name")

            # Parse the JSONL transcript for counts
            jsonl_file = json_file.with_suffix(".jsonl")
            user_msgs, assistant_msgs, tool_calls, prompt_wcs = self._parse_transcript(jsonl_file)

            # If no JSONL, try word counts from .history file
            if not prompt_wcs:
                history_file = json_file.with_suffix(".history")
                prompt_wcs = self._parse_history_word_counts(history_file)

            # Only include sessions with actual activity
            if user_msgs > 0 or assistant_msgs > 0:
                mcp_calls = sum(
                    c for name, c in tool_calls.items() if name not in KIRO_BUILTIN_TOOLS
                )
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
                        models=[],
                        prompt_word_counts=prompt_wcs,
                        extras={
                            "agent_name": agent_name,
                            "is_subagent": is_subagent,
                            "parent_session_id": meta.get("parent_session_id"),
                            "mcpToolCalls": mcp_calls,
                        },
                    )
                )

        return sessions

    def _scan_ide(
        self,
        project_filter: str | None = None,
        seen_ids: set[str] | None = None,
    ) -> list[Session]:
        """Scan Kiro IDE sessions from Application Support directories."""
        if seen_ids is None:
            seen_ids = set()

        sessions: list[Session] = []

        for ide_dir in self._ide_dirs:
            if not ide_dir.exists():
                continue

            # Scan global sessions + all workspace-sessions directories
            session_dirs = [ide_dir / "sessions"]
            ws_root = ide_dir / "workspace-sessions"
            if ws_root.is_dir():
                try:
                    for ws_dir in ws_root.iterdir():
                        if ws_dir.is_dir():
                            session_dirs.append(ws_dir)
                except OSError:
                    pass

            for sess_dir in session_dirs:
                if not sess_dir.is_dir():
                    continue

                # Read the sessions.json index for timestamps
                index_path = sess_dir / "sessions.json"
                index_data: list[dict] = []
                idx_text = safe_read_text(index_path)
                if idx_text:
                    try:
                        parsed = json.loads(idx_text)
                        if isinstance(parsed, list):
                            index_data = parsed
                    except (json.JSONDecodeError, ValueError):
                        pass

                # Build a lookup from sessionId → dateCreated (ms timestamp)
                date_lookup: dict[str, int] = {}
                workspace_lookup: dict[str, str | None] = {}
                for entry in index_data:
                    sid = entry.get("sessionId", "")
                    dc = entry.get("dateCreated")
                    if sid and dc:
                        try:
                            date_lookup[sid] = int(dc)
                        except (ValueError, TypeError):
                            pass
                    workspace_lookup[sid] = entry.get("workspaceDirectory")

                # Scan individual session JSON files
                try:
                    session_files = [
                        f for f in sess_dir.glob("*.json") if f.name != "sessions.json"
                    ]
                except OSError:
                    continue

                for sf in session_files:
                    text = safe_read_text(sf)
                    if not text:
                        continue
                    try:
                        sdata = json.loads(text)
                    except (json.JSONDecodeError, ValueError):
                        continue

                    session_id = sdata.get("sessionId")
                    if not session_id or session_id in seen_ids:
                        continue  # dedupe with CLI sessions

                    # Mark as seen BEFORE project filter to prevent
                    # duplicates when same session_id appears in both
                    # sessions/ and workspace-sessions/
                    seen_ids.add(session_id)

                    history = sdata.get("history", [])
                    if not history:
                        continue

                    # Apply project filter
                    workspace = sdata.get("workspaceDirectory") or workspace_lookup.get(session_id)
                    if project_filter and workspace:
                        if project_filter not in workspace:
                            continue

                    # Count messages and extract word counts
                    user_msgs = 0
                    assistant_msgs = 0
                    prompt_wcs: list[int] = []
                    models: set[str] = set()

                    for item in history:
                        msg = item.get("message", {})
                        role = msg.get("role")
                        if role == "user":
                            user_msgs += 1
                            content = msg.get("content", [])
                            wc = self._count_content_words(content)
                            if wc > 0:
                                prompt_wcs.append(wc)
                        elif role == "assistant":
                            assistant_msgs += 1

                        # Extract model from promptLogs
                        for log in item.get("promptLogs", []):
                            model = log.get("modelTitle")
                            if model:
                                models.add(model)

                    if user_msgs == 0 and assistant_msgs == 0:
                        continue

                    # Timestamp from index
                    started_at: datetime | None = None
                    ts_ms = date_lookup.get(session_id)
                    if ts_ms:
                        try:
                            started_at = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
                        except (OSError, ValueError):
                            pass

                    sessions.append(
                        Session(
                            tool="kiro",
                            session_id=session_id,
                            project_path=workspace,
                            started_at=started_at,
                            ended_at=None,  # IDE doesn't store end time
                            user_msgs=user_msgs,
                            assistant_msgs=assistant_msgs,
                            tool_calls_by_type={},  # IDE doesn't expose tool names
                            models=sorted(models),
                            prompt_word_counts=prompt_wcs,
                            extras={
                                "source": "ide",
                                "autonomyMode": sdata.get("autonomyMode"),
                                "sessionType": sdata.get("sessionType"),
                            },
                        )
                    )

        if sessions:
            _log(f"Kiro IDE: {len(sessions)} sessions from Application Support")

        return sessions

    def raw_data(self) -> dict | None:
        return self._raw

    # ── Private helpers ──────────────────────────────────────────────────

    def _parse_transcript(self, jsonl_path: Path) -> tuple[int, int, dict[str, int], list[int]]:
        """Parse a Kiro JSONL transcript for counts — never content.

        Kiro JSONL format (one JSON object per line):
          {"version":"v1","kind":"Prompt","data":{"message_id":"...","content":[...]}}
          {"version":"v1","kind":"AssistantMessage","data":{"message_id":"...","content":[...]}}
          {"version":"v1","kind":"ToolResults","data":{"message_id":"...","content":[...]}}

        From AssistantMessage content, we extract tool names from toolUse blocks.
        We count prompt word counts from Prompt entries (text length only).

        Note: CLI JSONL does not contain model info or per-event timestamps,
        so models and activeMinutes are not derived here.

        Returns (user_msgs, assistant_msgs, tool_calls_by_type, prompt_word_counts)
        """
        user_msgs = 0
        assistant_msgs = 0
        tool_calls: dict[str, int] = {}
        prompt_word_counts: list[int] = []

        text = safe_read_text(jsonl_path)
        if not text:
            return user_msgs, assistant_msgs, tool_calls, prompt_word_counts

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

        return user_msgs, assistant_msgs, tool_calls, prompt_word_counts

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
                    kind = block.get("kind")
                    if kind == "text":
                        text = block.get("data", "")
                        if isinstance(text, str):
                            total += len(text.split())
                    elif kind is not None and kind not in (
                        "toolUse",
                        "toolResult",
                    ):
                        _log(f"unknown content block kind: {kind!r}")
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
