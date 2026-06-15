# Data Collection Disclosure

Everything nextmillionai reads, derives, and never touches.

---

## Claude Code

| What is read | Derived signals | Never touched |
|---|---|---|
| `~/.claude/projects/**/*.jsonl` -- session ID, message count, user word count, tool-call counts (including MCP, read, and write tool breakdowns), model names, timestamps, git branch, working directory path | Total sessions, avg turns per task, avg prompt words, file/terminal tool ratios, MCP tool call count, read-to-edit ratio, peak productivity hour, streak days, session durations, max parallel agents (from timestamp overlaps), deep session count (sessions > 30 min), plan-mode percent | Raw prompt text, assistant responses, code blocks, file contents, `.env`/secrets |

## Cursor IDE

| What is read | Derived signals | Never touched |
|---|---|---|
| `~/.cursor/ai-tracking/ai-code-tracking.db` (`ai_code_hashes`, `scored_commits`, `conversation_summaries` tables) | AI code block counts, AI line survival rate, composer/tab ratios, conversation counts by model/mode | Raw code content, diff payloads, conversation bodies, prompt text, file contents |
| `~/.cursor/plans/*.plan.md` (file names + line counts only) | Plan count + complexity | Plan content, instructions, file references |
| `~/.cursor/mcp.json` + project `.cursor/mcp.json` (MCP server **names** only) | Counts toward the deduped MCP signal (names stay local — only the count feeds scoring) | Server commands, args, env, tokens, any config values beyond names |
| `~/.cursor/projects/*/agent-transcripts/` (directory sizes only) | Leverage ratio | Transcript content, agent prompts, agent responses |
| Cursor app storage `state.vscdb` (read-only sqlite; macOS `~/Library/Application Support/Cursor/User/`, Linux `~/.config/Cursor/User/`): composer entries' `createdAt`/`lastUpdatedAt`/`isAgentic` scalars + message COUNTS per composer; older versions' workspace `allComposers`/chat-tab timestamps | Session counts, hours (capped 8h/session), dates, agentic share — across all Cursor versions | Conversation bodies, prompt text, code blocks, file contents (values are reduced to scalar timestamps + counts; bubbles are counted by key, their content never parsed) |

## Codex CLI

| What is read | Derived signals | Never touched |
|---|---|---|
| `~/.codex/sessions/` -- file count only | Session count | Session content, prompts, responses |

## Git

| What is read | Derived signals | Never touched |
|---|---|---|
| `git log --oneline --since=6 months ago` per project | Commit count, feature/fix commit classification (from conventional-commit prefixes), detected languages/frameworks/tools, feature-to-fix ratio | Commit diffs, file contents, source code, `.env`, credentials |
| `package.json`/`pyproject.toml`/`go.mod`/`Cargo.toml` (dependency names only for framework detection) | Detected frameworks and tools | Dependency versions, lockfiles, source code |

## Wider tool field — OPT-IN (`other_tools`)

One consent question covers all of these (same privacy class: your own local
tool logs). Each adapter declares a fidelity tier; `counts`/`presence` sources
never invent sessions and never move a score. Full per-layout detail is in
[`docs/ADAPTERS.md`](docs/ADAPTERS.md).

| Tool | Tier | What is read | Never touched |
|---|---|---|---|
| Aider, Cline, Continue.dev, Copilot Chat, Zed AI | deep | each tool's own local session files: session boundaries, message counts, timestamps, models | message bodies beyond word/role counts, credentials |
| Windsurf, Cody | counts | store file counts + last-activity timestamp | session contents (format not parsed) |
| JetBrains AI | presence | IDE config markers (installed only) | chat history (not exposed locally) |

## Local model runtimes — OPT-IN (`local_models`)

| Runtime | Tier | What is read | Never touched |
|---|---|---|---|
| Ollama | counts | installed model tags; `history` line count | prompt/response contents |
| LM Studio | counts | model directory; conversation file counts | conversation contents |
| llama.cpp | presence | GGUF model cache presence | usage (no local usage log exists) |

## Custom adapters — OPT-IN (user-registered)

If you register a tool in `nextmillionai.config.json`, we read only the paths
and glob you declare — file-per-session timestamps (`mtime`) or presence — never
contents beyond what the declared format implies.

## Claude Desktop — experimental, low-fidelity, OPT-IN ONLY

Off by default, even with `--yes`. Enable it only by answering yes in
interactive `calibrate`.

| What is read | Derived signals | Never touched |
|---|---|---|
| Install directory presence; `claude_desktop_config.json` MCP server names | Integrations signal; when enabled, its MCP servers count toward the deduped MCP signal (names stay local — only the count feeds scoring) | Conversations (not stored locally by Claude Desktop), credentials, any config values beyond MCP server names |

## Local code scan (`assess --code`) — OPT-IN ONLY

| What is read | Derived signals | Never touched / never kept |
|---|---|---|
| Repo files (bounded walk: 4,000 files/repo, vendored dirs skipped): line counts, file names, manifest dependency names, config-file presence | Files/lines by language, test/doc presence, complexity hotspots (file name + line count), deploy configs, LLM-SDK/agent-framework detection for buildDomain | File contents (read to count, never stored), dependency versions, anything outside the scanned repos. All findings live under `experimental` — never in any shared or exported artifact |

---

The assessment path runs entirely on localhost: nothing is uploaded,
transmitted, or phoned home, and CI enforces it. The single exception is
the explicit, opt-in `nextmillionai publish`, which sends only the
visibility-filtered derived profile described in
[PRIVACY.md](PRIVACY.md) — and is revocable with `unpublish`. All
derived data stays in `~/.nextmillionai/data/`.
