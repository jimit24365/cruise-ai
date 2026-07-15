## What

Add Kiro (CLI & IDE) as a first-class adapter with `deep` fidelity — the same tier as Claude Code, Cursor, and Codex CLI.

Kiro is an AI coding assistant (by AWS) that stores rich session data at `~/.kiro/sessions/cli/`. The adapter reads session metadata, message counts, tool names, and timestamps — never prompt text or response content.

**Files:**
- `nextmillionai/adapters/kiro.py` — the adapter (337 lines)
- `nextmillionai/adapters/_registry.py` — register + consent-gate it
- `nextmillionai/scanner.py` — add `KIRO_SESSIONS_DIR` path constant
- `tests/test_adapters/test_kiro.py` — 16 tests with synthetic fixtures
- `docs/ADAPTERS.md` — document paths, fidelity, reads, derives
- `DATA_COLLECTION.md` — document privacy contract

## Why

Kiro is absent from the adapter list despite storing richer session data than some existing first-class tools:
- **Agent names** (`session_state.agent_name`) — which persona was active
- **Subagent orchestration** (`parent_session_id` + `session_created_reason: "subagent"`) — direct evidence of multi-agent dispatch
- **MCP tool diversity** — tool names include `jira`, `confluence`, `gitlab`, `dynacon`, `slack`, etc.
- **Configuration depth** — steering files, skills, rules, hooks, powers

This fills a tool gap for Kiro users who want their AI coding profile to reflect all their work, not just the sessions in Claude Code or Cursor.

Tested against 127 real sessions → 125 parseable, 2,572 user messages, 16,001 assistant messages, 14,039 tool calls, 95 subagent sessions across 3 months.

## Schema impact

- [x] No changes to `profile.json` or `scan_results.json` shape

The adapter produces standard `Session` objects and a `raw_data()` dict following the same contract as `codex.py`. No schema changes needed.

## Tests

- [ ] `ruff check .` passes
- [x] `pytest` passes — 16 new tests + all 94 existing adapter tests pass
- [x] Tested manually: ran `KiroAdapter().scan()` against real `~/.kiro/sessions/cli/` — 125 sessions parsed correctly with tool calls, subagent detection, and agent name extraction working

## Signals derived (maps to NMA dimensions)

| NMA Dimension | Kiro Signal |
|---|---|
| Orchestration Range | Distinct tool names (shell, jira, confluence, gitlab, dynacon), agent diversity, subagent dispatch count |
| Context Command | parent_session_id chains = multi-session orchestration |
| Signal Clarity | prompt_word_counts from .history files |
| Decision Weight | Agent name usage (intentional persona selection) |
