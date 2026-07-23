"""
cruise_ai.export -- Static, self-hostable artifact.

`cruise_ai export` renders the profile + report into a directory the
user can drop on any static host. The artifact contains ONLY the redacted
shareable JSON (visibility-filtered, allowlisted) — never experimental
signals, coverage, hidden projects, private growth, anti-patterns, or raw
prompt text. Both views read the same ./assessment.json.

Default = fully local: export writes to disk; nothing leaves the machine.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from cruise_ai.paths import STATIC_DIR, profile_path
from cruise_ai.schema import build_shareable_profile
from cruise_ai.visibility import load_visibility_config

# Keys that must never appear in an exported artifact, checked again
# post-redaction (belt + suspenders on top of the allowlist).
# growthAreas is intentionally NOT here: it is governed by the user's
# visibility config (private by default, explicit opt-in to share).
_FORBIDDEN_KEYS = {
    "experimental",
    "coverage",
    "antiPatterns",
    "growthEdge",
    "scannedProjects",
    "goToPrompt",
    "trajectory",
}


def _rewrite_for_static(html: str) -> str:
    """Make server-rooted paths work from a static directory."""
    html = html.replace('href="/static/', 'href="./static/')
    html = html.replace('src="/static/', 'src="./static/')
    html = html.replace('href="/report"', 'href="./report.html"')
    html = html.replace('href="/profile"', 'href="./index.html"')
    return html


def verify_artifact_json(shareable: dict) -> list[str]:
    """Return a list of violations found in the artifact JSON (empty = clean)."""
    violations: list[str] = []

    def walk(value, path=""):
        if isinstance(value, dict):
            for k, v in value.items():
                if k in _FORBIDDEN_KEYS:
                    violations.append(f"{path}.{k}" if path else k)
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, f"{path}[{i}]")

    walk(shareable)

    # No absolute filesystem paths may leak
    dumped = json.dumps(shareable)
    for m in re.finditer(r'"(/(?:Users|home|var|tmp)/[^"]*)"', dumped):
        violations.append(f"filesystem path: {m.group(1)[:60]}")

    return violations


def export_static(out_dir: str | Path) -> dict:
    """Build the static artifact. Returns a summary dict.

    Raises RuntimeError if no assessment exists or the redacted JSON
    fails the privacy verification.
    """
    src_profile = profile_path()
    if not src_profile.is_file():
        from cruise_ai.paths import cli_invocation

        raise RuntimeError(f"No assessment found. Run `{cli_invocation()} assess` first.")

    with open(src_profile) as f:
        profile = json.load(f)

    visibility = load_visibility_config()
    shareable = build_shareable_profile(profile, visibility)

    violations = verify_artifact_json(shareable)
    if violations:
        raise RuntimeError(
            "Refusing to export: private data detected in artifact: " + "; ".join(violations[:5])
        )

    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    # The one JSON both views read
    with open(out / "assessment.json", "w") as f:
        json.dump(shareable, f, indent=2, default=str)

    # Views (profile is the landing page)
    profile_html = (STATIC_DIR / "profile.html").read_text()
    report_html = (STATIC_DIR / "report.html").read_text()
    (out / "index.html").write_text(_rewrite_for_static(profile_html))
    (out / "report.html").write_text(_rewrite_for_static(report_html))

    # Agent-readable Markdown — rendered from the REDACTED shareable JSON,
    # so an agent (or a hiring tool) can read the profile/report without
    # parsing HTML, and it carries exactly what the shareable allows.
    from cruise_ai.markdown_export import profile_to_markdown

    (out / "profile.md").write_text(profile_to_markdown(shareable, "profile"))
    (out / "report.md").write_text(profile_to_markdown(shareable, "report"))

    # Assets
    for sub in ("css", "js"):
        src = STATIC_DIR / sub
        if src.is_dir():
            shutil.copytree(src, out / "static" / sub, dirs_exist_ok=True)

    return {
        "outDir": str(out),
        "files": sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()),
        "sections": sorted(shareable.keys()),
    }
