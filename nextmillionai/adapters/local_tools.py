"""
nextmillionai.adapters.local_tools — Adapters for the wider AI tool field.

Aider, Cline, Continue.dev, GitHub Copilot Chat, Windsurf, Zed AI,
JetBrains AI Assistant, Cody — plus a config-driven custom adapter so
users can register tools we don't know about (nextmillionai.config.json,
see docs/ADAPTERS.md).

Honesty contract — every adapter declares its FIDELITY:

  deep     — real session boundaries, timestamps, and message counts
             parsed from the tool's own local files.
  counts   — the tool exposes countable local artifacts (files, chats)
             but not parseable sessions; we count, we never invent.
             No Session objects are emitted — counts never become
             timeline or score evidence.
  presence — only installation/config is detectable; recorded as
             present, everything else marked insufficient.

What each tool genuinely exposes locally decides its tier; where a tool
exposes little, we collect what's there and say so in Provenance.
All reads are local files owned by the user; consent group:
``other_tools`` (one calibrate question, not eight).
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from nextmillionai.adapters._base import Session


def _log(msg: str) -> None:
    if os.environ.get("NEXTMILLIONAI_VERBOSE"):
        print(f"[scanner] {msg}", file=sys.stderr)


def _mtime_dt(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _safe_json(path: Path):
    try:
        return json.loads(path.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def _vscode_storage_roots(home: Path) -> list:
    """VS Code-family user dirs across variants + platforms.

    Extensions like Cline and Cody also run inside VS Code FORKS —
    Cursor, Windsurf — which keep the same User/globalStorage layout.
    Scanning only vanilla VS Code misses every fork-hosted install.
    """
    roots = []
    for base in (
        home / "Library" / "Application Support",  # macOS
        home / ".config",  # Linux
        home / "AppData" / "Roaming",  # Windows
    ):
        for variant in ("Code", "Code - Insiders", "VSCodium", "Cursor", "Windsurf"):
            d = base / variant / "User"
            if d.is_dir():
                roots.append(d)
    return roots


class _LocalToolAdapter:
    """Shared shape: detect roots, scan, expose raw with fidelity."""

    tool_id = "unknown"
    label = "Unknown tool"
    fidelity = "presence"

    def __init__(self, home: Path | None = None) -> None:
        self.home = home or Path.home()
        self._sessions: list = []
        self._raw: dict | None = None

    @property
    def name(self) -> str:
        return self.tool_id

    def detect(self) -> bool:  # pragma: no cover - overridden
        return False

    def scan(self, project_filter: str | None = None) -> list:
        if not self.detect():
            self._sessions, self._raw = [], None
            return []
        self._sessions, self._raw = self._scan_impl()
        if self._raw is not None:
            self._raw.setdefault("fidelity", self.fidelity)
            self._raw.setdefault("label", self.label)
        return self._sessions

    def raw_data(self) -> dict | None:
        return self._raw

    def _scan_impl(self) -> tuple:  # pragma: no cover - overridden
        return [], None


# ── Aider (deep: chat history files carry real session markers) ─────────────

_AIDER_SESSION_RE = re.compile(r"^#+ aider chat started at (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


class AiderAdapter(_LocalToolAdapter):
    """Aider writes ``.aider.chat.history.md`` per repo with explicit
    "aider chat started at <ts>" markers — real sessions, parsed, not
    guessed. Repos come from the previous scan's git discovery plus the
    home dir itself."""

    tool_id = "aider"
    label = "Aider"
    fidelity = "deep"

    def _candidate_files(self) -> list:
        files = []
        seen = set()
        # Home-level config marks the install; history files live in repos
        for root in self._repo_roots():
            f = root / ".aider.chat.history.md"
            if f.is_file() and str(f) not in seen:
                seen.add(str(f))
                files.append(f)
        return files

    def _repo_roots(self) -> list:
        roots = [self.home]
        try:
            from nextmillionai.paths import scan_results_path

            sr = scan_results_path()
            if sr.is_file():
                data = json.loads(sr.read_text())
                for proj in (data.get("git") or {}).get("projects") or []:
                    if proj.get("path"):
                        roots.append(Path(proj["path"]))
        except (json.JSONDecodeError, OSError):
            pass
        return roots

    def detect(self) -> bool:
        if (self.home / ".aider.conf.yml").is_file() or (self.home / ".aider").is_dir():
            return True
        return bool(self._candidate_files())

    def _scan_impl(self) -> tuple:
        sessions = []
        files = self._candidate_files()
        for f in files:
            try:
                text = f.read_text(errors="replace")
            except OSError:
                continue
            current_start = None
            user_msgs = 0
            project = str(f.parent)

            def _flush(start, msgs, end_ts, project=project):
                if start is None:
                    return
                sessions.append(
                    Session(
                        tool="aider",
                        session_id=f"aider:{project}:{start.isoformat()}",
                        project_path=project,
                        started_at=start,
                        ended_at=end_ts or start,
                        user_msgs=msgs,
                        assistant_msgs=0,
                    )
                )

            for line in text.splitlines():
                m = _AIDER_SESSION_RE.match(line)
                if m:
                    _flush(current_start, user_msgs, None)
                    try:
                        current_start = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(
                            tzinfo=timezone.utc
                        )
                    except ValueError:
                        current_start = None
                    user_msgs = 0
                elif line.startswith("#### "):
                    user_msgs += 1
            _flush(current_start, user_msgs, _mtime_dt(f))

        raw = {
            "historyFiles": len(files),
            "sessions": len(sessions),
            "note": "Sessions parsed from .aider.chat.history.md markers.",
        }
        _log(f"Aider: {len(sessions)} sessions in {len(files)} history files")
        return sessions, raw


# ── Cline (deep: VS Code globalStorage task dirs) ────────────────────────────


class ClineAdapter(_LocalToolAdapter):
    tool_id = "cline"
    label = "Cline"
    fidelity = "deep"

    def _task_dirs(self) -> list:
        dirs: list = []
        for user_dir in _vscode_storage_roots(self.home):
            for ext_id in ("saoudrizwan.claude-dev", "cline.cline"):
                tasks = user_dir / "globalStorage" / ext_id / "tasks"
                if tasks.is_dir():
                    dirs.extend(d for d in tasks.iterdir() if d.is_dir())
        return dirs

    def detect(self) -> bool:
        return bool(self._task_dirs())

    def _scan_impl(self) -> tuple:
        sessions = []
        for task_dir in self._task_dirs():
            # Dir name is a ms-epoch timestamp
            started = None
            try:
                ts = int(task_dir.name)
                started = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                pass

            user_msgs = assistant_msgs = 0
            conv = _safe_json(task_dir / "api_conversation_history.json")
            if isinstance(conv, list):
                for msg in conv:
                    role = msg.get("role") if isinstance(msg, dict) else None
                    if role == "user":
                        user_msgs += 1
                    elif role == "assistant":
                        assistant_msgs += 1
            if not (user_msgs or assistant_msgs):
                ui = _safe_json(task_dir / "ui_messages.json")
                if isinstance(ui, list):
                    user_msgs = sum(1 for m in ui if isinstance(m, dict) and m.get("type") == "ask")
                    assistant_msgs = sum(
                        1 for m in ui if isinstance(m, dict) and m.get("type") == "say"
                    )
            if started or user_msgs or assistant_msgs:
                ended = _mtime_dt(task_dir)
                sessions.append(
                    Session(
                        tool="cline",
                        session_id=f"cline:{task_dir.name}",
                        started_at=started,
                        ended_at=ended if (started and ended and ended > started) else started,
                        user_msgs=user_msgs,
                        assistant_msgs=assistant_msgs,
                    )
                )
        raw = {"tasks": len(sessions), "note": "Tasks from VS Code globalStorage."}
        _log(f"Cline: {len(sessions)} tasks")
        return sessions, raw


# ── Continue.dev (deep: ~/.continue/sessions) ────────────────────────────────


class ContinueAdapter(_LocalToolAdapter):
    tool_id = "continue"
    label = "Continue.dev"
    fidelity = "deep"

    def _sessions_dir(self) -> Path:
        return self.home / ".continue" / "sessions"

    def detect(self) -> bool:
        return self._sessions_dir().is_dir()

    def _scan_impl(self) -> tuple:
        sdir = self._sessions_dir()
        index = _safe_json(sdir / "sessions.json")
        meta_by_id = {}
        if isinstance(index, list):
            for entry in index:
                if isinstance(entry, dict) and entry.get("sessionId"):
                    meta_by_id[entry["sessionId"]] = entry

        sessions = []
        for f in sorted(sdir.glob("*.json")):
            if f.name == "sessions.json":
                continue
            data = _safe_json(f)
            if not isinstance(data, dict):
                continue
            sid = data.get("sessionId") or f.stem
            history = data.get("history") or []
            user_msgs = assistant_msgs = 0
            models = set()
            for item in history:
                if not isinstance(item, dict):
                    continue
                msg = item.get("message") or {}
                role = msg.get("role")
                if role == "user":
                    user_msgs += 1
                elif role == "assistant":
                    assistant_msgs += 1
                model = (item.get("completionOptions") or {}).get("model") or msg.get("model")
                if model:
                    models.add(str(model))
            meta = meta_by_id.get(sid) or {}
            started = None
            date_created = meta.get("dateCreated") or data.get("dateCreated")
            if date_created:
                try:
                    val = float(date_created)
                    if val > 1e12:
                        val /= 1000.0
                    started = datetime.fromtimestamp(val, tz=timezone.utc)
                except (ValueError, TypeError, OSError):
                    started = None
            if started is None:
                started = _mtime_dt(f)
            project = meta.get("workspaceDirectory") or None
            if user_msgs or assistant_msgs:
                sessions.append(
                    Session(
                        tool="continue",
                        session_id=f"continue:{sid}",
                        project_path=project,
                        started_at=started,
                        ended_at=_mtime_dt(f) or started,
                        user_msgs=user_msgs,
                        assistant_msgs=assistant_msgs,
                        models=sorted(models),
                    )
                )
        raw = {"sessions": len(sessions), "note": "Sessions from ~/.continue/sessions."}
        _log(f"Continue.dev: {len(sessions)} sessions")
        return sessions, raw


# ── GitHub Copilot Chat (deep-ish: VS Code workspaceStorage chatSessions) ────


class CopilotChatAdapter(_LocalToolAdapter):
    tool_id = "copilot_chat"
    label = "GitHub Copilot Chat"
    fidelity = "deep"

    def _chat_files(self) -> list:
        files: list = []
        for user_dir in _vscode_storage_roots(self.home):
            # Copilot runs in vanilla VS Code only — never read a fork's
            # chatSessions (Cursor/Windsurf chats are theirs, not Copilot's)
            if user_dir.parent.name not in ("Code", "Code - Insiders", "VSCodium"):
                continue
            ws = user_dir / "workspaceStorage"
            if not ws.is_dir():
                continue
            for d in ws.iterdir():
                cs = d / "chatSessions"
                if cs.is_dir():
                    files.extend(f for f in cs.glob("*.json"))
        return files

    def detect(self) -> bool:
        return bool(self._chat_files())

    def _scan_impl(self) -> tuple:
        sessions = []
        for f in self._chat_files():
            data = _safe_json(f)
            if not isinstance(data, dict):
                continue
            requests = data.get("requests") or []
            user_msgs = len(requests)
            if not user_msgs:
                continue
            started = None
            created = data.get("creationDate")
            if created:
                try:
                    val = float(created)
                    if val > 1e12:
                        val /= 1000.0
                    started = datetime.fromtimestamp(val, tz=timezone.utc)
                except (ValueError, TypeError, OSError):
                    started = None
            if started is None:
                started = _mtime_dt(f)
            sessions.append(
                Session(
                    tool="copilot_chat",
                    session_id=f"copilot:{f.stem}",
                    started_at=started,
                    ended_at=_mtime_dt(f) or started,
                    user_msgs=user_msgs,
                    assistant_msgs=user_msgs,  # one response per request
                )
            )
        raw = {"chats": len(sessions), "note": "Chat sessions from VS Code workspaceStorage."}
        _log(f"Copilot Chat: {len(sessions)} chats")
        return sessions, raw


# ── Windsurf (counts: cascade store is binary — never invented) ─────────────


class WindsurfAdapter(_LocalToolAdapter):
    tool_id = "windsurf"
    label = "Windsurf"
    fidelity = "counts"

    def _roots(self) -> list:
        return [
            d
            for d in (
                self.home / ".codeium" / "windsurf",
                self.home / "Library" / "Application Support" / "Windsurf",
                self.home / ".config" / "Windsurf",
            )
            if d.is_dir()
        ]

    def detect(self) -> bool:
        return bool(self._roots())

    def _scan_impl(self) -> tuple:
        file_count = 0
        latest = None
        for root in self._roots():
            cascade = root / "cascade"
            scan_root = cascade if cascade.is_dir() else root
            try:
                for f in scan_root.rglob("*"):
                    if f.is_file():
                        file_count += 1
                        dt = _mtime_dt(f)
                        if dt and (latest is None or dt > latest):
                            latest = dt
                    if file_count > 5000:
                        break
            except OSError:
                continue
        raw = {
            "files": file_count,
            "lastActivity": latest.isoformat() if latest else None,
            "note": (
                "Windsurf stores Cascade history in a non-parseable local "
                "format; counted, sessions marked insufficient."
            ),
        }
        _log(f"Windsurf: present ({file_count} store files)")
        return [], raw


# ── Zed AI (deep for legacy conversations; counts for threads.db) ───────────


class ZedAdapter(_LocalToolAdapter):
    tool_id = "zed_ai"
    label = "Zed AI"
    fidelity = "deep"

    def _base_dirs(self) -> list:
        return [
            d
            for d in (
                self.home / "Library" / "Application Support" / "Zed",
                self.home / ".local" / "share" / "zed",
            )
            if d.is_dir()
        ]

    def detect(self) -> bool:
        for base in self._base_dirs():
            if (base / "conversations").is_dir() or (base / "threads").is_dir():
                return True
        return False

    def _scan_impl(self) -> tuple:
        sessions = []
        threads_count = 0
        for base in self._base_dirs():
            conv_dir = base / "conversations"
            if conv_dir.is_dir():
                for f in sorted(conv_dir.glob("*.json")):
                    data = _safe_json(f)
                    if not isinstance(data, dict):
                        continue
                    msgs = data.get("messages") or data.get("message_metadata") or []
                    user_msgs = 0
                    assistant_msgs = 0
                    if isinstance(msgs, list):
                        for m in msgs:
                            role = (m.get("role") if isinstance(m, dict) else "") or ""
                            if role.lower() in ("user", "human"):
                                user_msgs += 1
                            elif role.lower() == "assistant":
                                assistant_msgs += 1
                    started = _mtime_dt(f)
                    if user_msgs or assistant_msgs:
                        sessions.append(
                            Session(
                                tool="zed_ai",
                                session_id=f"zed:{f.stem}",
                                started_at=started,
                                ended_at=started,
                                user_msgs=user_msgs,
                                assistant_msgs=assistant_msgs,
                            )
                        )
            threads_db = base / "threads" / "threads.db"
            if threads_db.is_file():
                try:
                    import sqlite3

                    con = sqlite3.connect(f"file:{threads_db}?mode=ro", uri=True)
                    try:
                        cur = con.execute("SELECT COUNT(*) FROM threads")
                        threads_count += int(cur.fetchone()[0])
                    finally:
                        con.close()
                except Exception:
                    pass
        raw = {
            "conversations": len(sessions),
            "threads": threads_count,
            "note": "Conversations parsed; threads.db counted only.",
        }
        _log(f"Zed AI: {len(sessions)} conversations, {threads_count} threads")
        return sessions, raw


# ── JetBrains AI Assistant (presence: chats are not locally parseable) ──────


class JetBrainsAIAdapter(_LocalToolAdapter):
    tool_id = "jetbrains_ai"
    label = "JetBrains AI Assistant"
    fidelity = "presence"

    def _ide_dirs(self) -> list:
        hits = []
        for base in (
            self.home / "Library" / "Application Support" / "JetBrains",
            self.home / ".config" / "JetBrains",
            self.home / "AppData" / "Roaming" / "JetBrains",
        ):
            if not base.is_dir():
                continue
            try:
                for ide in base.iterdir():
                    if not ide.is_dir():
                        continue
                    # AI Assistant leaves option/plugin artifacts
                    for marker in (
                        ide / "options" / "AIAssistant.xml",
                        ide / "options" / "aiAssistant.xml",
                        ide / "plugins" / "ml-llm",
                    ):
                        if marker.exists():
                            hits.append(ide.name)
                            break
            except OSError:
                continue
        return hits

    def detect(self) -> bool:
        return bool(self._ide_dirs())

    def _scan_impl(self) -> tuple:
        ides = self._ide_dirs()
        raw = {
            "ides": ides,
            "note": (
                "AI Assistant detected in: "
                + ", ".join(ides)
                + ". Chat history is not exposed in a parseable local "
                "format — usage marked insufficient, never estimated."
            ),
        }
        _log(f"JetBrains AI: present in {len(ides)} IDE configs")
        return [], raw


# ── Cody (counts: globalStorage artifacts) ───────────────────────────────────


class CodyAdapter(_LocalToolAdapter):
    tool_id = "cody"
    label = "Cody"
    fidelity = "counts"

    def _storage_dirs(self) -> list:
        return [
            user_dir / "globalStorage" / "sourcegraph.cody-ai"
            for user_dir in _vscode_storage_roots(self.home)
            if (user_dir / "globalStorage" / "sourcegraph.cody-ai").is_dir()
        ]

    def detect(self) -> bool:
        return bool(self._storage_dirs())

    def _scan_impl(self) -> tuple:
        chat_files = 0
        latest = None
        for d in self._storage_dirs():
            try:
                for f in d.rglob("*.json"):
                    chat_files += 1
                    dt = _mtime_dt(f)
                    if dt and (latest is None or dt > latest):
                        latest = dt
            except OSError:
                continue
        raw = {
            "storageFiles": chat_files,
            "lastActivity": latest.isoformat() if latest else None,
            "note": "Cody storage counted; chat format is account-coupled, not parsed.",
        }
        _log(f"Cody: present ({chat_files} storage files)")
        return [], raw


# ── Custom adapters (nextmillionai.config.json) ──────────────────────────────


class CustomLogAdapter(_LocalToolAdapter):
    """User-registered tool: the user told us where their tool logs live.

    Config (nextmillionai.config.json):
      {"adapters": [{"id": "mytool", "label": "My Tool",
                     "path": "~/.mytool/sessions", "glob": "*.jsonl",
                     "format": "file-per-session" | "presence"}]}

    file-per-session: one Session per matched file, timestamps from file
    mtime (explicitly tagged ``timestampFidelity: mtime`` — the user
    registered this source knowingly). presence: detected + counted only.
    """

    fidelity = "counts"

    def __init__(self, spec: dict, home: Path | None = None) -> None:
        super().__init__(home)
        self.spec = spec
        self.tool_id = str(spec.get("id") or "custom")
        self.label = str(spec.get("label") or self.tool_id)
        self.root = Path(os.path.expanduser(str(spec.get("path") or "")))
        self.glob = str(spec.get("glob") or "*")
        self.format = str(spec.get("format") or "file-per-session")
        if self.format == "presence":
            self.fidelity = "presence"

    @property
    def name(self) -> str:
        return self.tool_id

    def detect(self) -> bool:
        return bool(self.spec.get("path")) and self.root.exists()

    def _scan_impl(self) -> tuple:
        files = []
        if self.root.is_dir():
            try:
                files = sorted(f for f in self.root.rglob(self.glob) if f.is_file())
            except OSError:
                files = []
        elif self.root.is_file():
            files = [self.root]

        sessions = []
        if self.format == "file-per-session":
            for f in files:
                started = _mtime_dt(f)
                if not started:
                    continue
                sessions.append(
                    Session(
                        tool=self.tool_id,
                        session_id=f"{self.tool_id}:{f.name}",
                        started_at=started,
                        ended_at=started,
                        user_msgs=0,
                        assistant_msgs=0,
                        extras={"timestampFidelity": "mtime", "custom": True},
                    )
                )
        raw = {
            "files": len(files),
            "custom": True,
            "note": f"User-registered adapter ({self.format}); timestamps from file mtime.",
        }
        _log(f"{self.label} (custom): {len(files)} files")
        return sessions, raw


def load_custom_adapters(home: Path | None = None) -> list:
    """Custom adapters from nextmillionai.config.json (if any)."""
    from nextmillionai.paths import config_path

    cfg_file = config_path()
    if not cfg_file:
        return []
    cfg = _safe_json(cfg_file)
    if not isinstance(cfg, dict):
        return []
    adapters = []
    reserved = {a.tool_id for a in get_local_tool_adapters(home)} | {
        "claude_code",
        "cursor",
        "codex",
        "git",
        "claude_desktop",
    }
    for spec in cfg.get("adapters") or []:
        if not isinstance(spec, dict) or not spec.get("id") or not spec.get("path"):
            continue
        if str(spec["id"]) in reserved:
            continue
        adapters.append(CustomLogAdapter(spec, home=home))
    return adapters


def get_local_tool_adapters(home: Path | None = None) -> list:
    """All built-in wider-field adapters, scan order."""
    return [
        AiderAdapter(home=home),
        ClineAdapter(home=home),
        ContinueAdapter(home=home),
        CopilotChatAdapter(home=home),
        WindsurfAdapter(home=home),
        ZedAdapter(home=home),
        JetBrainsAIAdapter(home=home),
        CodyAdapter(home=home),
    ]
