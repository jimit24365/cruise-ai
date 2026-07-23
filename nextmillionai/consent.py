"""
nextmillionai.consent -- First-run consent and data-collection disclosure.

Manages user consent for scanning each data source. Consent state
is persisted to ``~/.nextmillionai/data/consent.json``.

Collection scope (day-window, repos filter) is persisted to
``~/.nextmillionai/data/collection_config.json``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from nextmillionai.paths import collection_config_path, data_dir

CONSENT_VERSION = "1.0"

ALL_SOURCES = {
    "claude_code": "Claude Code (~/.claude/projects/)",
    "cursor": "Cursor IDE (~/.cursor/ + its app storage: composer session timestamps)",
    "codex": "Codex CLI (~/.codex/sessions/)",
    "kiro": "Kiro (~/.kiro/sessions/cli/ + Kiro IDE app storage)",
    "git": "Git (commit history + dependency names)",
    "other_tools": (
        "Other AI tools' local logs (VS Code: Copilot Chat / Cline / Cody, "
        "plus Continue, Aider, OpenCode, Windsurf, Zed, Antigravity, JetBrains AI "
        "+ custom adapters)"
    ),
    "local_models": "Local model runtimes (Ollama, LM Studio, llama.cpp GGUF caches)",
    "claude_desktop": "Claude Desktop (experimental, low-fidelity: install + MCP config only)",
}

# Sources that are never enabled without an explicit yes — even with --yes.
# Claude Desktop is experimental and low-fidelity; opting in must be deliberate.
OPT_IN_ONLY_SOURCES = {"claude_desktop"}


def consent_path() -> Path:
    """Path to the consent state file."""
    return data_dir() / "consent.json"


def load_consent() -> dict | None:
    """Load consent.json, return None if missing or invalid."""
    p = consent_path()
    if not p.is_file():
        return None
    try:
        with open(p) as f:
            data = json.load(f)
        if not isinstance(data, dict) or "sources" not in data:
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def save_consent(sources: dict[str, bool]) -> None:
    """Write consent.json with version, timestamp, and per-source toggles."""
    data = {
        "consent_version": CONSENT_VERSION,
        "consented_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
    }
    p = consent_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(data, f, indent=2)


def reset_consent() -> None:
    """Delete consent.json if it exists."""
    p = consent_path()
    if p.is_file():
        p.unlink()


def consented_sources(consent: dict) -> dict[str, bool]:
    """Extract source toggles from a consent dict."""
    return dict(consent.get("sources", {}))


# Per-source disclosure text, keyed by ALL_SOURCES key so a subset can be
# printed (e.g. when a new source is added after the user already calibrated).
_DISCLOSURE_BLOCKS: dict[str, list[str]] = {
    "claude_code": [
        "Claude Code",
        "  Read:    Session metadata from ~/.claude/projects/",
        "  Derived: Session counts, tool ratios, model usage",
        "  Never:   Raw prompts, responses, code, secrets",
    ],
    "cursor": [
        "Cursor IDE",
        "  Read:    AI tracking DB, plan file names, transcript sizes,",
        "           composer session timestamps from Cursor's own",
        "           state.vscdb (read-only; all storage generations)",
        "  Derived: AI code counts, survival rate, composer ratios,",
        "           session counts + hours + dates",
        "  Never:   Code content, diffs, conversation bodies, prompts",
    ],
    "codex": [
        "Codex CLI",
        "  Read:    Session JSONL from ~/.codex/sessions/ — roles, models,",
        "           tool-call names, timestamps, prompt word counts",
        "  Derived: Session counts + hours, models, tool usage,",
        "           prompt-length distribution",
        "  Never:   Prompt text, responses, code, tool payloads",
    ],
    "kiro": [
        "Kiro (CLI + IDE)",
        "  Read:    Session metadata + transcript counts from",
        "           ~/.kiro/sessions/cli/ and Kiro IDE app storage",
        "           (tool names, timestamps, prompt word counts)",
        "  Derived: Session counts + hours, tool usage, subagent",
        "           orchestration, prompt word counts, models (IDE)",
        "  Never:   Prompt text, responses, code, secrets, titles",
    ],
    "git": [
        "Git",
        "  Read:    Commit log (oneline), dependency names",
        "  Derived: Commit counts, languages, frameworks",
        "  Never:   Diffs, file contents, source code, credentials",
    ],
    "other_tools": [
        "Other AI tools — VS Code (Copilot Chat / Cline / Cody),",
        "Continue, Aider, OpenCode, Windsurf, Zed, Antigravity, JetBrains AI, custom adapters",
        "  Read:    Each tool's own local logs/storage (VS Code",
        "           globalStorage/workspaceStorage, ~/.continue, repo",
        "           .aider history, Zed conversations, ...)",
        "  Derived: Session counts + timestamps where the tool exposes",
        "           them; file counts/presence otherwise — fidelity is",
        "           declared per tool in Provenance, never invented",
        "  Never:   Prompts, responses, code, secrets",
    ],
    "local_models": [
        "Local model runtimes (Ollama, LM Studio, llama.cpp)",
        "  Read:    Model manifests/caches + usage counters the runtime",
        "           itself writes (e.g. ~/.ollama/history line count)",
        "  Derived: Installed model names, prompt/chat counts",
        "  Never:   Prompt or chat content",
    ],
    "claude_desktop": [
        "Claude Desktop (experimental, low-fidelity, opt-in)",
        "  Read:    Install presence, MCP server names from config",
        "  Derived: Integration breadth signal (experimental only)",
        "  Never:   Conversations (not stored locally), scores unaffected",
    ],
}


def print_disclosure(only: list[str] | None = None) -> None:
    """Print an abbreviated data-collection summary to stdout.

    *only*: restrict the per-source blocks to these ALL_SOURCES keys
    (used when prompting for sources added after the user calibrated).
    """
    print()
    print("  DATA COLLECTION DISCLOSURE")
    print("  " + "=" * 42)
    print()
    print("  nextmillionai scans local AI session data")
    print("  to build your coding profile. Here is what")
    print("  each source accesses:")
    print()
    for key, lines in _DISCLOSURE_BLOCKS.items():
        if only is not None and key not in only:
            continue
        for line in lines:
            print(f"  {line}")
        print()
    print("  All data stays on your machine. Nothing is uploaded.")
    print("  Full details: DATA_COLLECTION.md")
    print()


def _ask_source(key: str, description: str, existing: dict[str, bool]) -> bool:
    """Ask one y/n consent question for a source, honoring saved answers.

    Defaults to the saved answer when one exists; otherwise yes for
    standard sources and no for opt-in-only ones.
    """
    opt_in_only = key in OPT_IN_ONLY_SOURCES
    has_saved = key in existing
    default_yes = existing[key] if has_saved else not opt_in_only
    hint = "[Y/n]" if default_yes else "[y/N]"
    current = f" (currently {'on' if existing[key] else 'off'})" if has_saved else ""
    while True:
        answer = input(f"  Allow scanning {description}?{current} {hint} ").strip().lower()
        if answer in ("y", "yes") or (answer == "" and default_yes):
            return True
        elif answer in ("n", "no") or (answer == "" and not default_yes):
            return False
        else:
            print("    Please enter y or n.")


def default_enabled_sources() -> dict[str, bool]:
    """Default source toggles when no consent exists: every standard
    source on, opt-in-only sources off.

    The single source of truth for scan defaults — ``run_adapters`` and
    ``run_scan`` derive their fallback dicts from here so a new source
    added to ALL_SOURCES can never silently miss a default. (A drifted
    hand-written copy of this dict is exactly how the Kiro adapter
    shipped consent-gated off everywhere.)
    """
    return {key: key not in OPT_IN_ONLY_SOURCES for key in ALL_SOURCES}


def prompt_new_sources(missing: list[str], existing: dict[str, bool]) -> dict[str, bool]:
    """Mini consent prompt for sources added since the user last calibrated.

    Prints the disclosure for JUST those sources, asks each one (default
    yes unless opt-in-only), and returns the FULL merged sources dict.
    Existing answers are never re-asked or changed.
    """
    print()
    plural = "S" if len(missing) > 1 else ""
    print(f"  NEW DATA SOURCE{plural}")
    print("  A scanner was added since you last calibrated. Your")
    print("  existing choices are unchanged; only the new source" + plural.lower() + " below")
    print("  need an answer.")
    print_disclosure(only=missing)
    sources = dict(existing)
    for key in missing:
        sources[key] = _ask_source(key, ALL_SOURCES[key], existing)
    enabled = [k for k in missing if sources[k]]
    print()
    if enabled:
        print(f"  Consent saved. Newly enabled: {', '.join(enabled)}")
    else:
        print("  Consent saved. New source" + (plural.lower() or "") + " left off.")
    print()
    return sources


def prompt_consent(non_interactive: bool = False) -> dict[str, bool]:
    """Interactive consent flow — STICKY across re-runs.

    A consent already given is never silently dropped: every prompt
    defaults to your saved answer (shown as "currently on/off"), and
    pressing Enter keeps it. ``--yes`` enables all standard sources and
    PRESERVES previous explicit choices for opt-in-only sources instead
    of resetting them to off.
    Returns ``{source_key: bool}`` dict.
    """
    prior = load_consent()
    existing: dict[str, bool] = consented_sources(prior) if prior else {}

    if non_interactive:
        # Maximal for standard sources; opt-in-only sources keep a prior
        # explicit answer (a given consent must survive --yes re-runs)
        # and stay off when never answered. Disclosure still prints —
        # consent is informed even when non-interactive.
        print_disclosure()
        return {
            key: existing.get(key, False) if key in OPT_IN_ONLY_SOURCES else True
            for key in ALL_SOURCES
        }

    print_disclosure()

    sources: dict[str, bool] = {}
    for key, description in ALL_SOURCES.items():
        sources[key] = _ask_source(key, description, existing)

    enabled = [k for k, v in sources.items() if v]
    print()
    if enabled:
        print(f"  Consent saved. Enabled: {', '.join(enabled)}")
    else:
        print("  All sources disabled. Profile will have limited data.")
    print()
    return sources


# ── Collection config ────────────────────────────────────────────────────────


def default_collection_config() -> dict:
    """Return the maximal (default) collection config."""
    return {"window": "all", "repos": "all"}


def load_collection_config() -> dict | None:
    """Load collection_config.json, return None if missing or invalid."""
    p = collection_config_path()
    if not p.is_file():
        return None
    try:
        with open(p) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def save_collection_config(config: dict) -> None:
    """Write collection_config.json with timestamp."""
    config["configured_at"] = datetime.now(timezone.utc).isoformat()
    p = collection_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(config, f, indent=2)


def prompt_collection_scope(non_interactive: bool = False) -> dict:
    """Interactive collection scope flow.

    If *non_interactive* (``--yes``), return maximal defaults.
    Otherwise, prompt for day-window and repo filter.
    Returns ``{"window": "all"|int, "repos": "all"|list[str]}``.
    """
    if non_interactive:
        return default_collection_config()

    print()
    print("  COLLECTION SCOPE")
    print("  " + "-" * 42)
    print("  Default is maximal (all sources, all repos, all time).")
    print("  You can narrow the scope below.")
    print()

    # Day window
    while True:
        answer = input("  Day window [7/30/90/all/custom] (default: all): ").strip().lower()
        if answer in ("", "all"):
            window: str | int = "all"
            break
        elif answer in ("7", "30", "90"):
            window = int(answer)
            break
        elif answer == "custom":
            try:
                days = int(input("    Enter number of days: ").strip())
                if days > 0:
                    window = days
                    break
                print("    Must be a positive number.")
            except ValueError:
                print("    Enter a valid number.")
        else:
            print("    Please enter 7, 30, 90, all, or custom.")

    # Repo filter
    while True:
        answer = input("  Repos to scan [all/select] (default: all): ").strip().lower()
        if answer in ("", "all"):
            repos: str | list[str] = "all"
            break
        elif answer == "select":
            paths_input = input("    Enter repo paths (comma-separated): ").strip()
            if paths_input:
                repos = [p.strip() for p in paths_input.split(",") if p.strip()]
                break
            print("    No paths entered, using all.")
            repos = "all"
            break
        else:
            print("    Please enter 'all' or 'select'.")

    config = {"window": window, "repos": repos}
    print()
    print(f"  Collection scope: window={window}, repos={repos}")
    print()
    return config
