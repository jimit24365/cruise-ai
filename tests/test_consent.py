"""Tests for the nextmillionai consent module."""

import re
from pathlib import Path

from nextmillionai.consent import (
    CONSENT_VERSION,
    consented_sources,
    load_consent,
    prompt_consent,
    reset_consent,
    save_consent,
)


def test_save_and_load_consent(tmp_path, monkeypatch):
    """Round-trip: save consent then load it back."""
    monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path))
    sources = {"claude_code": True, "cursor": False, "codex": True, "git": True}
    save_consent(sources)

    consent = load_consent()
    assert consent is not None
    assert consent["consent_version"] == CONSENT_VERSION
    assert consent["sources"] == sources
    assert "consented_at" in consent


def test_reset_consent(tmp_path, monkeypatch):
    """reset_consent removes the consent file."""
    monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path))
    save_consent({"claude_code": True, "cursor": True, "codex": True, "git": True})
    assert load_consent() is not None

    reset_consent()
    assert load_consent() is None


def test_prompt_consent_yes_flag(tmp_path, monkeypatch):
    """Non-interactive mode enables all standard sources; experimental
    opt-in-only sources (claude_desktop) stay off when never answered."""
    from nextmillionai.consent import OPT_IN_ONLY_SOURCES

    monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path))
    sources = prompt_consent(non_interactive=True)
    assert all(v is True for k, v in sources.items() if k not in OPT_IN_ONLY_SOURCES)
    assert all(sources[k] is False for k in OPT_IN_ONLY_SOURCES)
    assert "claude_code" in sources
    assert "cursor" in sources
    assert "codex" in sources
    assert "git" in sources
    assert "other_tools" in sources
    assert "local_models" in sources


def test_yes_flag_preserves_prior_opt_in(tmp_path, monkeypatch):
    """A consent the user already gave must survive `calibrate --yes` —
    re-running non-interactively never silently revokes claude_desktop."""
    monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path))
    save_consent({"claude_code": True, "claude_desktop": True})
    sources = prompt_consent(non_interactive=True)
    assert sources["claude_desktop"] is True


def test_interactive_defaults_to_saved_answers(tmp_path, monkeypatch):
    """Re-running calibrate shows saved answers as defaults — pressing
    Enter keeps every prior choice (incl. opt-in-only ON and standard OFF)."""
    monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path))
    save_consent({"claude_code": True, "cursor": False, "claude_desktop": True})

    prompts = []

    def fake_input(prompt):
        prompts.append(prompt)
        return ""  # Enter = keep the default

    monkeypatch.setattr("builtins.input", fake_input)
    sources = prompt_consent(non_interactive=False)
    assert sources["claude_code"] is True
    assert sources["cursor"] is False  # saved OFF stays off
    assert sources["claude_desktop"] is True  # saved opt-in stays ON
    # the prompts say so, honestly
    joined = " ".join(prompts)
    assert "(currently on)" in joined
    assert "(currently off)" in joined
    # VS Code is named in the wider-tools question
    assert "VS Code" in joined


def test_consented_sources_extracts_toggles(tmp_path, monkeypatch):
    """consented_sources extracts the sources dict from a consent object."""
    monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path))
    sources = {"claude_code": True, "cursor": False, "codex": True, "git": True}
    save_consent(sources)
    consent = load_consent()
    result = consented_sources(consent)
    assert result == sources


def test_load_consent_returns_none_when_missing(tmp_path, monkeypatch):
    """load_consent returns None when no consent file exists."""
    monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path))
    assert load_consent() is None


def test_no_outbound_network_calls():
    """Verify no Python source files import outbound networking libraries.

    Excludes test files, the hub.py server (uses http.server for localhost),
    and stdlib server-side imports.
    """
    # Only match actual import statements or direct calls, not string literals
    # used as dictionary keys/values for framework detection maps.
    import_patterns = [
        r"^\s*import\s+urllib\b",
        r"^\s*from\s+urllib\b",
        r"^\s*import\s+requests\b",
        r"^\s*from\s+requests\b",
        r"^\s*import\s+httpx\b",
        r"^\s*from\s+httpx\b",
        r"^\s*import\s+http\.client\b",
        r"^\s*from\s+http\.client\b",
        r"\burlopen\s*\(",
        r"\bsocket\.connect\s*\(",
    ]
    combined = re.compile("|".join(import_patterns))

    src_dir = Path(__file__).resolve().parent.parent / "nextmillionai"
    violations = []

    for py_file in sorted(src_dir.rglob("*.py")):
        # Skips:
        #   - test files
        #   - hub.py / network_server.py: localhost servers (http.server,
        #     inbound only)
        #   - network.py: THE one sanctioned outbound module — the explicit
        #     opt-in publish path, never imported by the assessment path
        #     (enforced by test_assessment_path_never_imports_network below)
        rel = py_file.relative_to(src_dir)
        if str(rel).startswith("test") or rel.name in ("hub.py", "network.py", "network_server.py"):
            continue

        text = py_file.read_text()
        for i, line in enumerate(text.splitlines(), 1):
            # Skip comments
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if combined.search(line):
                violations.append(f"{rel}:{i}: {line.strip()}")

    assert violations == [], "Outbound network imports found in source files:\n" + "\n".join(
        violations
    )


def test_assessment_path_never_imports_network():
    """Promise (a): no server in the assessment path. The opt-in outbound
    client (network.py) may only be imported inside cmd_publish/cmd_unpublish/
    cmd_network/cmd_sync — the explicit user-initiated outbound commands —
    never at module level and never from scan/score/serve/enrich/export
    code. (sync is outbound like publish: the user pushes derived-only
    snapshots to a repo THEY own; the merge itself is local sync_merge.py.)"""
    src_dir = Path(__file__).resolve().parent.parent / "nextmillionai"
    pattern = re.compile(r"^\s*(import|from)\s+nextmillionai\.network\b")

    violations = []
    for py_file in sorted(src_dir.rglob("*.py")):
        rel = py_file.relative_to(src_dir)
        if rel.name in ("network.py", "network_server.py"):
            continue
        in_publish_cmd = False
        for i, line in enumerate(py_file.read_text().splitlines(), 1):
            if re.match(r"^def cmd_(publish|unpublish|network|sync)\b", line):
                in_publish_cmd = True
            elif re.match(r"^(def|class)\s", line):
                in_publish_cmd = False
            if pattern.match(line) and not in_publish_cmd:
                violations.append(f"{rel}:{i}: {line.strip()}")

    assert violations == [], (
        "network client imported outside the explicit publish commands:\n" + "\n".join(violations)
    )
