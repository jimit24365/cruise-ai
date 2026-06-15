"""Methodology 0.4.4 — MCP signal: all clients + usage, reward-only.

Guards the blind-spot fix: MCP servers are counted across every consented
client (Claude Code + Cursor + Claude Desktop), deduped by name; a genuine
zero is reward-only (never drags the dimension); MCP tool-call usage credits
Context Command.
"""

from __future__ import annotations

import json

from nextmillionai.scanner import count_mcp_servers
from nextmillionai.scoring import score_context_command, score_orchestration_range


def _write(path, servers):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": {name: {} for name in servers}}))


# ── count_mcp_servers: union across clients, deduped ──────────────────────────


def test_unions_and_dedupes_across_clients(tmp_path):
    _write(tmp_path / ".claude.json", ["a"])
    _write(tmp_path / ".cursor" / "mcp.json", ["b", "c", "intent-hub"])
    count, names = count_mcp_servers(
        tmp_path, [], cursor_enabled=True, desktop_servers=["intent-hub", "d"]
    )
    # a + b + c + intent-hub + d  (intent-hub appears twice → counted once)
    assert count == 5
    assert names == ["a", "b", "c", "d", "intent-hub"]


def test_cursor_gated_on_consent(tmp_path):
    _write(tmp_path / ".claude.json", ["a"])
    _write(tmp_path / ".cursor" / "mcp.json", ["b", "c"])
    count, _ = count_mcp_servers(tmp_path, [], cursor_enabled=False)
    assert count == 1  # Cursor config ignored when its source isn't consented


def test_project_level_configs(tmp_path):
    proj = tmp_path / "repo"
    _write(proj / ".mcp.json", ["proj-claude"])
    _write(proj / ".cursor" / "mcp.json", ["proj-cursor"])
    count, names = count_mcp_servers(tmp_path, [{"path": str(proj)}], cursor_enabled=True)
    assert count == 2
    assert names == ["proj-claude", "proj-cursor"]


def test_genuine_zero(tmp_path):
    count, names = count_mcp_servers(tmp_path, [], cursor_enabled=True)
    assert count == 0
    assert names == []


# ── scoring: reward-only + usage-aware ────────────────────────────────────────


def _ctx_inp(**overrides):
    base = {
        "referenceUsageRate": 0.5,
        "totalScoredCommits": 100,
        "totalSessions": 200,
        "projectCount": 10,
        "firstShotAcceptRate": 0.8,
        "aiUsageSpanDays": 120,
        "deepSessionCount": 60,
        "activeSurfaceCount": 2,
        "mcpServerCount": 0,
        "mcpToolCalls": 0,
    }
    base.update(overrides)
    return base


def test_zero_mcp_is_reward_only_not_penalized():
    """A genuine zero must score the SAME as omitting the key entirely —
    i.e. it's dropped from the average, never a 0 that drags the dimension."""
    with_zero = score_context_command(_ctx_inp(mcpServerCount=0, mcpToolCalls=0))["score"]
    inp = _ctx_inp()
    del inp["mcpServerCount"]
    del inp["mcpToolCalls"]
    without_key = score_context_command(inp)["score"]
    assert with_zero == without_key


def test_mcp_servers_reward_when_present():
    low = score_context_command(_ctx_inp(mcpServerCount=0))["score"]
    high = score_context_command(_ctx_inp(mcpServerCount=5))["score"]
    assert high > low


def test_mcp_usage_lifts_context_command():
    no_usage = score_context_command(_ctx_inp(mcpToolCalls=0))["score"]
    usage = score_context_command(_ctx_inp(mcpToolCalls=100))["score"]
    assert usage > no_usage
    ev = score_context_command(_ctx_inp(mcpToolCalls=100))["evidence"]
    assert any("MCP tool calls" in e for e in ev)


def test_orchestration_mcp_reward_only():
    orch = {
        "uniqueToolCount": 3,
        "maxParallelAgents": 2,
        "modelCount": 2,
        "totalSessions": 100,
        "mcpServerCount": 0,
    }
    with_zero = score_orchestration_range(dict(orch))["score"]
    no_key = dict(orch)
    del no_key["mcpServerCount"]
    assert with_zero == score_orchestration_range(no_key)["score"]
