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
    "git": "Git (commit history + dependency names)",
    "other_tools": (
        "Other AI tools' local logs (VS Code: Copilot Chat / Cline / Cody, "
        "plus Continue, Aider, Windsurf, Zed, JetBrains AI + custom adapters)"
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


def print_disclosure() -> None:
    """Print an abbreviated data-collection summary to stdout."""
    print()
    print("  DATA COLLECTION DISCLOSURE")
    print("  " + "=" * 42)
    print()
    print("  nextmillionai scans local AI session data")
    print("  to build your coding profile. Here is what")
    print("  each source accesses:")
    print()
    print("  Claude Code")
    print("    Read:    Session metadata from ~/.claude/projects/")
    print("    Derived: Session counts, tool ratios, model usage")
    print("    Never:   Raw prompts, responses, code, secrets")
    print()
    print("  Cursor IDE")
    print("    Read:    AI tracking DB, plan file names, transcript sizes,")
    print("             composer session timestamps from Cursor's own")
    print("             state.vscdb (read-only; all storage generations)")
    print("    Derived: AI code counts, survival rate, composer ratios,")
    print("             session counts + hours + dates")
    print("    Never:   Code content, diffs, conversation bodies, prompts")
    print()
    print("  Codex CLI")
    print("    Read:    Session file count from ~/.codex/sessions/")
    print("    Derived: Session count")
    print("    Never:   Session content, prompts, responses")
    print()
    print("  Git")
    print("    Read:    Commit log (oneline), dependency names")
    print("    Derived: Commit counts, languages, frameworks")
    print("    Never:   Diffs, file contents, source code, credentials")
    print()
    print("  Other AI tools — VS Code (Copilot Chat / Cline / Cody),")
    print("  Continue, Aider, Windsurf, Zed, JetBrains AI, custom adapters")
    print("    Read:    Each tool's own local logs/storage (VS Code")
    print("             globalStorage/workspaceStorage, ~/.continue, repo")
    print("             .aider history, Zed conversations, ...)")
    print("    Derived: Session counts + timestamps where the tool exposes")
    print("             them; file counts/presence otherwise — fidelity is")
    print("             declared per tool in Provenance, never invented")
    print("    Never:   Prompts, responses, code, secrets")
    print()
    print("  Local model runtimes (Ollama, LM Studio, llama.cpp)")
    print("    Read:    Model manifests/caches + usage counters the runtime")
    print("             itself writes (e.g. ~/.ollama/history line count)")
    print("    Derived: Installed model names, prompt/chat counts")
    print("    Never:   Prompt or chat content")
    print()
    print("  Claude Desktop (experimental, low-fidelity, opt-in)")
    print("    Read:    Install presence, MCP server names from config")
    print("    Derived: Integration breadth signal (experimental only)")
    print("    Never:   Conversations (not stored locally), scores unaffected")
    print()
    print("  All data stays on your machine. Nothing is uploaded.")
    print("  Full details: DATA_COLLECTION.md")
    print()


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
        opt_in_only = key in OPT_IN_ONLY_SOURCES
        has_saved = key in existing
        default_yes = existing[key] if has_saved else not opt_in_only
        hint = "[Y/n]" if default_yes else "[y/N]"
        current = f" (currently {'on' if existing[key] else 'off'})" if has_saved else ""
        while True:
            answer = input(f"  Allow scanning {description}?{current} {hint} ").strip().lower()
            if answer in ("y", "yes") or (answer == "" and default_yes):
                sources[key] = True
                break
            elif answer in ("n", "no") or (answer == "" and not default_yes):
                sources[key] = False
                break
            else:
                print("    Please enter y or n.")

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
