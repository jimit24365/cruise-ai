"""
nextmillionai.adapters.codex -- Codex CLI adapter (deepened).

Parses JSONL session files from ``~/.codex/sessions/`` to extract
messages, models, tool calls, and timestamps -- not just file counts.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from nextmillionai.adapters._base import Session
from nextmillionai.scanner import CODEX_SESSIONS_DIR, safe_read_text


def _log(msg: str) -> None:
    if os.environ.get("NEXTMILLIONAI_VERBOSE"):
        print(f"[scanner] {msg}", file=sys.stderr)


class CodexAdapter:
    """Adapter that scans Codex CLI sessions with deep JSONL parsing."""

    def __init__(self, *, sessions_dir: Path | None = None) -> None:
        self._sessions_dir = sessions_dir or CODEX_SESSIONS_DIR
        self._sessions: list[Session] = []
        self._raw: dict | None = None

    @property
    def name(self) -> str:
        return "codex"

    def detect(self) -> bool:
        return self._sessions_dir.exists()

    def scan(self, project_filter: str | None = None) -> list[Session]:
        if not self.detect():
            _log("Codex CLI: ~/.codex/sessions/ not found, skipping")
            self._sessions = []
            self._raw = None
            return []

        _log("Codex CLI: scanning sessions...")

        # Codex changed its layout across versions: old releases wrote
        # flat ``sessions/*.jsonl``; current releases nest by date,
        # ``sessions/YYYY/MM/DD/rollout-*.jsonl``. rglob covers both —
        # flat-only scanning silently returns zero sessions on any
        # up-to-date install.
        try:
            session_files = sorted(f for f in self._sessions_dir.rglob("*.jsonl") if f.is_file())
        except Exception:
            self._sessions = []
            self._raw = None
            return []

        # Also count non-JSONL files for backward compat
        try:
            all_files = sorted(f for f in self._sessions_dir.rglob("*") if f.is_file())
        except Exception:
            all_files = session_files

        if not all_files:
            self._sessions = []
            self._raw = None
            return []

        sessions: list[Session] = []
        total_user_msgs = 0
        total_assistant_msgs = 0
        all_models: dict[str, int] = {}

        for sf in session_files:
            text = safe_read_text(sf)
            if not text:
                continue

            session_id = sf.stem
            user_msgs = 0
            assistant_msgs = 0
            models: set[str] = set()
            tool_calls: dict[str, int] = {}
            earliest_ts: datetime | None = None
            latest_ts: datetime | None = None
            active_sec = 0.0
            prev_dt: datetime | None = None
            prompt_word_counts: list[int] = []
            cwd: str | None = None

            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Extract cwd if present
                if cwd is None and obj.get("cwd"):
                    cwd = obj["cwd"]

                # Parse timestamp
                created_at = obj.get("created_at") or obj.get("timestamp")
                if created_at is not None:
                    try:
                        ts_val = float(created_at)
                        if ts_val > 1e12:
                            ts_val = ts_val / 1000.0
                        dt = datetime.fromtimestamp(ts_val, tz=timezone.utc)
                        if earliest_ts is None or dt < earliest_ts:
                            earliest_ts = dt
                        if latest_ts is None or dt > latest_ts:
                            latest_ts = dt
                        # Gap-based active time (idle >30min never counts)
                        if prev_dt is not None:
                            gap = (dt - prev_dt).total_seconds()
                            if 0 <= gap <= 1800:
                                active_sec += gap
                        prev_dt = dt
                    except (ValueError, TypeError, OSError):
                        pass

                msg_type = obj.get("type", "")
                role = obj.get("role", "")

                # Codex JSONL: {"type":"message","role":"user",...}
                if msg_type == "message" or role:
                    actual_role = role or msg_type
                    if actual_role == "user":
                        user_msgs += 1
                        content = obj.get("content", "")
                        if isinstance(content, str):
                            wc = len(content.split())
                            prompt_word_counts.append(wc)
                        elif isinstance(content, list):
                            wc = 0
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    wc += len(block.get("text", "").split())
                            prompt_word_counts.append(wc)
                    elif actual_role == "assistant":
                        assistant_msgs += 1
                        model = obj.get("model")
                        if model:
                            models.add(model)
                            all_models[model] = all_models.get(model, 0) + 1

                        # Count tool calls in assistant content
                        content = obj.get("content", [])
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") in (
                                    "tool_use",
                                    "function_call",
                                ):
                                    tc_name = block.get("name", "unknown")
                                    tool_calls[tc_name] = tool_calls.get(tc_name, 0) + 1

                # Also handle {"type":"function_call",...} style entries
                elif msg_type == "function_call":
                    tc_name = obj.get("name", "unknown")
                    tool_calls[tc_name] = tool_calls.get(tc_name, 0) + 1

            total_user_msgs += user_msgs
            total_assistant_msgs += assistant_msgs

            if user_msgs > 0 or assistant_msgs > 0:
                sessions.append(
                    Session(
                        tool="codex",
                        session_id=session_id,
                        project_path=cwd,
                        started_at=earliest_ts,
                        ended_at=latest_ts,
                        user_msgs=user_msgs,
                        assistant_msgs=assistant_msgs,
                        tool_calls_by_type=tool_calls,
                        models=sorted(models),
                        prompt_word_counts=prompt_word_counts,
                        extras={"activeMinutes": round(active_sec / 60.0, 1)},
                    )
                )

        session_count = len(all_files)
        parsed_count = len(sessions)

        if parsed_count > 0:
            _log(f"Codex CLI: {parsed_count} parsed sessions ({session_count} files total)")
        else:
            _log(f"Codex CLI: {session_count} sessions")

        # Compute earliest/latest across all parsed sessions
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

        self._sessions = sessions
        self._raw = {
            "total_sessions": session_count,
            "parsed_sessions": parsed_count,
            "total_user_msgs": total_user_msgs,
            "total_assistant_msgs": total_assistant_msgs,
            "models_used": all_models,
            "path": str(self._sessions_dir),
            "earliest": all_earliest,
            "latest": all_latest,
        }

        return sessions

    def raw_data(self) -> dict | None:
        return self._raw
