# Tool coverage — the data contract

This is the canonical record of **every tool we read, which versions of
it we support, exactly what we read, and what we derive**. It is core
product surface: if a tool or layout isn't listed here, we don't read
it; if a claim here is wrong, that's a bug. The privacy ledger
([`DATA_COLLECTION.md`](../DATA_COLLECTION.md)) states what is *never*
touched; this file states what *is*.

Standing rules, enforced in code and tests:

1. **Local files only, read-only.** No subprocess to any tool, no
   network (privacy CI), sqlite opened `mode=ro`.
2. **Every adapter declares fidelity** (shown in Provenance):
   `deep` = real session boundaries + timestamps parsed from the tool's
   own files · `counts` = countable artifacts, no parseable sessions ·
   `presence` = install detectable, usage marked **insufficient**.
3. **All storage generations.** Tools move their data between versions;
   adapters read every layout we know, dedupe across them, and this doc
   lists each one. Older layouts are never dropped.
4. **Durations are estimates, uniformly:** first-to-last activity per
   session, capped at 8h — labeled as estimated, never sold as tracked
   wall-clock.
5. **Measured history never regresses.** Every dated session enters the
   local ledger (`~/.nextmillionai/data/history/`); when a tool prunes
   its store, totals (sessions, hours, span, longest session, deep
   sessions, dispatches, agent runtime) are superseded from the ledger
   via `max()`.
6. **Counts/presence sources never invent sessions** and never move
   scores — provenance and coverage only.

## First-class tools (own consent question each)

### Claude Code — `deep`

| | |
|---|---|
| Paths | `~/.claude/projects/` (all OSes) |
| Generations | **flat**: `<project>/<session-id>.jsonl` (all versions) · **subagents** (newer): `<project>/<session-id>/subagents/agent-*.jsonl` |
| Read | JSONL session metadata: timestamps, roles, tool_use names, models, prompt word counts (text reduced to counts) |
| Derived | sessions, hours, span, prompts, plan-mode, dispatches (Task calls **and** subagent run files, max), **agent runtime hours** (run-file spans, kept separate from user hours), models, per-day activity |
| Notes | Claude Code prunes old transcripts — ledger preserves what was measured |

### Cursor — `deep`

| | |
|---|---|
| Paths | `~/.cursor/` (tracking db, plans, transcripts, **`mcp.json` server names** for the MCP count) **+ app storage** `state.vscdb`: macOS `~/Library/Application Support/Cursor/User/`, Linux `~/.config/Cursor/User/`, Windows `%APPDATA%/Cursor/User/` |
| Generations | **gen 3 (current)**: global `cursorDiskKV` → `composerData:*` scalars (`createdAt`/`lastUpdatedAt`/`isAgentic`) + `bubbleId:*` message counts (counted by key — content never parsed) · **gen 2**: workspace `ItemTable composer.composerData → allComposers[]` (+ project from `workspace.json`) · **gen 1 (oldest)**: workspace `aichat` chat tabs (`lastSendTime`) |
| Read | composer timestamps + counts; `ai-code-tracking.db` (`ai_code_hashes`, `scored_commits`, `conversation_summaries`); plan file names; transcript dir sizes |
| Derived | sessions + hours + dates + agentic share (all generations, deduped by composerId — global wins post-migration), AI code counts, survival rate, composer/tab ratios, models/modes |
| Notes | conversation-summary placeholders are skipped when composer history exists (same chats — no double count) |

### Codex CLI — `deep`

| | |
|---|---|
| Paths | `~/.codex/sessions/` (all OSes) |
| Generations | **flat** (older): `sessions/*.jsonl` · **date-nested** (current): `sessions/YYYY/MM/DD/rollout-*.jsonl` — discovered recursively |
| Read | JSONL: roles, timestamps, models, tool/function calls, prompt word counts |
| Derived | sessions, hours, span, models, per-day activity |

### git — `deep`

| | |
|---|---|
| Paths | repos discovered from session working dirs + configured roots |
| Read | `git log --oneline` (+ dates), dependency **names** from manifests (root + one level of monorepo workspaces: `apps/*`, `packages/*`, `services/*`) |
| Monorepos (`--code`) | every sub-package with its own manifest is classified separately (any workspace flavor — pnpm/yarn/npm/lerna/nx/turbo — reduces to "a dir with a manifest"); repo verdict: an LLM behind product code in ANY package → `ai_products` (vendored agent/dev tooling stays internal); infra-only packages → `ai_systems`. A nested `.git` is a repo BOUNDARY: a vendored clone/submodule is its own scan unit — its code never feeds the parent's metrics or verdict, so the same code is never classified twice |
| Derived | commit counts/dates, languages, frameworks, build-domain markers, feature/fix ratio |

## Wider tool field (one `other_tools` consent question)

VS Code-family extension hosts scanned for the extensions below:
vanilla **Code**, **Code - Insiders**, **VSCodium**, and the forks
**Cursor** and **Windsurf** — macOS `~/Library/Application Support/<host>/User/`,
Linux `~/.config/<host>/User/`, Windows `%APPDATA%/<host>/User/`.

### Cline — `deep`
Task dirs `globalStorage/{saoudrizwan.claude-dev,cline.cline}/tasks/<ms-epoch>/`
in ANY host above. Reads `api_conversation_history.json` roles (fallback
`ui_messages.json` ask/say); dir name = start timestamp. Derived:
sessions, hours, message counts.

### GitHub Copilot Chat — `deep`
`workspaceStorage/*/chatSessions/*.json` in **vanilla VS Code variants
only** — a fork's `chatSessions` belong to the fork, never counted as
Copilot. Reads request counts + `creationDate`. Derived: sessions, dates.

### Continue.dev — `deep`
`~/.continue/sessions/` (all OSes): `sessions.json` index +
per-session JSON. Reads roles, models, `dateCreated`, workspace dir.

### Aider — `deep`
`.aider.chat.history.md` per repo (repos from git discovery + home);
install marker `~/.aider*`. Parses the explicit
`# aider chat started at <ts>` session markers + `####` prompt lines.

### Zed AI — `deep`
macOS `~/Library/Application Support/Zed/`, Linux `~/.local/share/zed/`.
`conversations/*.json` parsed (roles); `threads/threads.db` **counted
only** (schema is internal).

### Windsurf — `counts`
`~/.codeium/windsurf/` + app dirs. Cascade store is a binary internal
format — files counted, last-activity noted, sessions marked
**insufficient** (never reverse-engineered into fake sessions).

### Cody — `counts`
`globalStorage/sourcegraph.cody-ai/` in any host. Storage files counted;
chat format is account-coupled, not parsed.

### Antigravity — `counts`
Google's agentic IDE (a VS Code fork from the former Windsurf team).
Trajectories live as per-session Protobuf files at
`~/.gemini/antigravity/conversations/*.pb` with plan/walkthrough "brain"
artifacts under `~/.gemini/antigravity/brain/`; the sidebar index is a VS
Code `state.vscdb` under an `Antigravity` / `Antigravity IDE`
`User/globalStorage/` dir (macOS `~/Library/Application Support/`, Linux
`~/.config/`, Windows `%APPDATA%/`). The `.pb` store is not a parseable
session log — trajectories + brain tasks are counted, last-activity noted,
sessions marked **insufficient** (never reverse-engineered into fake
sessions), same as the sibling Cascade store.

### JetBrains AI Assistant — `presence`
IDE config markers (`options/AIAssistant.xml`, `plugins/ml-llm`) under
macOS `~/Library/Application Support/JetBrains/<IDE>/`, Linux
`~/.config/JetBrains/`, Windows `%APPDATA%/JetBrains/`. Chat history is
not exposed in a parseable local format — recorded as present, usage
insufficient.

### Claude Desktop — `presence` (opt-in only, experimental)
Install presence + MCP server names from config. Presence stays
experimental, but when this opt-in source is enabled its configured MCP
servers count toward the deduped MCP signal (Context Command /
Orchestration Range), alongside Claude Code and Cursor — server names stay
local, only the count feeds scoring (methodology `0.4.4`).

## Local model runtimes (one `local_models` consent question)

| Runtime | Read | Derived |
|---|---|---|
| Ollama | `~/.ollama/models/manifests/` + `~/.ollama/history` line count | installed models, prompt count |
| LM Studio | `~/.lmstudio/{models,conversations}` (+ `~/.cache/lm-studio`) | models, chat file count |
| llama.cpp | GGUF files in `~/.cache/llama.cpp`, `~/models` | model cache only — no usage log exists, run counts stay insufficient |

## Custom tools (no code)

Register any tool in `nextmillionai.config.json`:

```json
{"adapters": [{"id": "mytool", "label": "My Tool",
  "path": "~/.mytool/sessions", "glob": "*.jsonl",
  "format": "file-per-session"}]}
```

`file-per-session` = one session per matched file, mtime timestamps
(explicitly tagged `timestampFidelity: mtime`); `presence` = counted
only. Lives under the `other_tools` consent group.

The same file also carries your identity fields (name, title, …). It is
read from `~/.nextmillionai/nextmillionai.config.json` first (the durable
home, so identity + custom adapters persist across repo clones), falling
back to `./nextmillionai.config.json` in the current directory.

## When a tool ships a new storage layout

That's a coverage bug. Open an issue with the tool version and the new
path — or a PR adding the generation to the adapter, a fixture test
(`tests/test_adapters/`), and a row here. The adapter contract:

```python
class MyToolAdapter:
    @property
    def name(self) -> str: ...        # stable tool id
    def detect(self) -> bool: ...     # cheap local presence check
    def scan(self, project_filter=None) -> list[Session]: ...
    def raw_data(self) -> dict | None: ...  # MUST include "fidelity" + "note"
```

House rules for PRs: local files only; declare fidelity honestly;
sessions need real timestamps parsed from content (mtime is reserved
for user-registered custom adapters); fixtures, never live data, in
tests (`tests/conftest.py` guards real stores); update this doc,
`DATA_COLLECTION.md`, the consent disclosure, `_registry`, and the
`_tool_labels` maps (`build_profile.py`, `static/js/profile.js`).
