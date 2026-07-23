"""Shared-tab CSS must live in tabs-shared.css — one home, both views.

The Work / Lab / Provenance / Share tabs are rendered ONCE by
``static/js/tabs-shared.js`` and shown in BOTH the profile and the report
views. Profile loads ``profile.css`` + ``tabs-shared.css``; report loads
``report.css`` + ``tabs-shared.css`` — and NEVER the other view's sheet. So
any class the shared renderer emits must be styled in ``tabs-shared.css``: if
a shared class is styled only in a per-page sheet, the OTHER view renders it
unstyled (e.g. the green "on profile" badge that triggered this guard).

The rule, CI-enforced: shared-tab styles go in tabs-shared.css, never in
profile.css / report.css. An agent that adds one to the wrong sheet fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

_STATIC = Path(__file__).resolve().parent.parent / "cruise_ai" / "static"

# Base/contextual classes that are page-specific by design — variants of base
# selectors (``.btn.dark``, ``hr.div``, ``.tag`` / ``.tag.dom``) defined
# identically in BOTH page sheets, so both views are already styled. These are
# not shared-tab item styles. Keep this set tiny and documented.
_ALLOW = {"dark", "div", "dom", "tag"}


def _classes_rendered_by_shared_js() -> set[str]:
    js = (_STATIC / "js" / "tabs-shared.js").read_text()
    out: set[str] = set()
    for literal in re.findall(r'class="([^"]+)"', js):
        for tok in literal.split():
            # skip template-literal fragments / interpolated bits
            if tok and "'" not in tok and "+" not in tok and "{" not in tok:
                out.add(tok)
    return out


def _styled_in(css: str, cls: str) -> bool:
    return re.search(r"\." + re.escape(cls) + r"(?![\w-])", css) is not None


def test_shared_tab_classes_live_in_tabs_shared_css():
    css = _STATIC / "css"
    profile = (css / "profile.css").read_text()
    report = (css / "report.css").read_text()
    shared = (css / "tabs-shared.css").read_text()

    offenders = []
    for cls in sorted(_classes_rendered_by_shared_js()):
        if cls in _ALLOW or _styled_in(shared, cls):
            continue
        pages = [
            name
            for name, text in (("profile.css", profile), ("report.css", report))
            if _styled_in(text, cls)
        ]
        if pages:
            offenders.append(f".{cls}  (only in {', '.join(pages)})")

    assert not offenders, (
        "These classes are rendered by the SHARED static/js/tabs-shared.js "
        "(shown in both the profile and report views) but styled only in a "
        "per-page sheet — so the view that doesn't load that sheet renders them "
        "unstyled. Move them to static/css/tabs-shared.css:\n  " + "\n  ".join(offenders)
    )


def _root_vars(css: str) -> set[str]:
    m = re.search(r":root\s*\{([^}]*)\}", css)
    return set(re.findall(r"(--[\w-]+)\s*:", m.group(1))) if m else set()


def _used_vars(css: str) -> set[str]:
    return set(re.findall(r"var\(\s*(--[\w-]+)", css))


def test_shared_css_vars_defined_in_both_page_roots():
    """tabs-shared.css carries no :root of its own — it resolves CSS variables
    from whichever page loaded it. So every var it uses must be defined in BOTH
    profile.css and report.css :root, or the view whose root lacks it renders
    that element unstyled (the --green-bg / --blue-bg class of bug)."""
    css = _STATIC / "css"
    profile_root = _root_vars((css / "profile.css").read_text())
    report_root = _root_vars((css / "report.css").read_text())

    missing = []
    for v in sorted(_used_vars((css / "tabs-shared.css").read_text())):
        absent = [
            name
            for name, root in (("profile.css", profile_root), ("report.css", report_root))
            if v not in root
        ]
        if absent:
            missing.append(f"{v}  (not in {', '.join(absent)} :root)")

    assert not missing, (
        "tabs-shared.css is loaded by both views, so every CSS variable it uses "
        "must be defined in BOTH page :root blocks:\n  " + "\n  ".join(missing)
    )
