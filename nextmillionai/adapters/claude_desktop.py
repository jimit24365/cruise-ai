"""
nextmillionai.adapters.claude_desktop -- Claude Desktop adapter.

Experimental, low-fidelity, opt-in (default OFF). Claude Desktop does not
store conversation transcripts locally in an open format, so this adapter
honestly emits NO sessions. What it can measure:

  - presence of a Claude Desktop install
  - MCP servers configured in claude_desktop_config.json (names only)

These surface as experimental signals only — they never change scores.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from nextmillionai.adapters._base import Session


def default_desktop_dir() -> Path:
    """Platform-specific Claude Desktop application-support directory."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude"
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Claude"
        return Path.home() / "AppData" / "Roaming" / "Claude"
    return Path.home() / ".config" / "Claude"


class ClaudeDesktopAdapter:
    """Low-fidelity adapter: detects install + MCP config, no transcripts."""

    def __init__(self, desktop_dir: Path | None = None):
        self.desktop_dir = desktop_dir or default_desktop_dir()
        self._raw: dict | None = None

    @property
    def name(self) -> str:
        return "claude_desktop"

    def detect(self) -> bool:
        return self.desktop_dir.is_dir()

    def scan(self, project_filter: str | None = None) -> list[Session]:
        """No parseable transcripts exist locally — emit zero sessions.

        We refuse to fabricate activity from cache-file mtimes; the only
        honest signals are install presence and the MCP config.
        """
        mcp_servers: list[str] = []
        config_file = self.desktop_dir / "claude_desktop_config.json"
        if config_file.is_file():
            try:
                config = json.loads(config_file.read_text())
                servers = config.get("mcpServers")
                if isinstance(servers, dict):
                    mcp_servers = sorted(servers.keys())
            except (json.JSONDecodeError, OSError):
                pass

        self._raw = {
            "detected": True,
            "fidelity": "low",
            "experimental": True,
            "mcpServers": mcp_servers,
            "mcpServerCount": len(mcp_servers),
            "sessionsReadable": False,
            "note": (
                "Claude Desktop stores conversations server-side; only the "
                "install and MCP configuration are measurable locally."
            ),
        }
        return []

    def raw_data(self) -> dict | None:
        return self._raw
