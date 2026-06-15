"""Render parity — no surface may silently drop fields from the assessment.

The profile JSON is the one source of truth; every surface is a projection
of it (CLAUDE.md value #4). Data freshness is guaranteed by the engine
regenerating profile.json each scan and the surfaces rendering from it on
demand. What regeneration CANNOT guarantee is *coverage*: a renderer that
has no line for `harness` will never show it, no matter how fresh the data.

These tests close that gap for the two render surfaces:

  - **Markdown** (markdown_export.py): scope is the *shareable* profile — md
    is the shareable-class summary (the export path renders the redacted JSON).
    "Rendered?" = the field is accessed by quoted literal in the module source.

  - **HTML** (static/js/profile.js, report.js, tabs-shared.js): scope is the
    *full* profile — the served views render everything locally, including the
    private analytics (leverage, coverage, lab) the md deliberately omits.
    "Rendered?" = the field is read off the raw JSON / transformed view object
    (a root-anchored property-access scan). This is a deliberately weaker,
    cheaper guarantee than executing the JS — it proves a field is *read by a
    view*, not pixel-rendered — because this Python-gated repo has no JS
    runtime, and a static scan still catches the high-value drift (a field that
    NO view touches). Golden-DOM snapshots would need a jsdom/Node stack this
    repo intentionally doesn't carry.

Both are self-maintaining: the field set comes from the bundled example the
engine actually produced, and "is it rendered?" is answered by grepping the
real source (like tests/test_docs_truth.py greps shipped CSS/JS). The only
hand-kept lists are WAIVED / HTML_WAIVED — small, structural, each reasoned.
"""

import json
import re
from pathlib import Path

from nextmillionai import markdown_export
from nextmillionai.markdown_export import _GLOSSARY, _collect_numbers, profile_to_markdown
from nextmillionai.schema import build_shareable_profile

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = json.loads((ROOT / "nextmillionai" / "examples" / "profile.json").read_text())
MD_SOURCE = (ROOT / "nextmillionai" / "markdown_export.py").read_text()

# Top-level shareable fields deliberately NOT rendered as Markdown prose, each
# with a reason. Adding a field here is the deliberate "don't surface it"
# decision — the counterpart to rendering it. Keep this list honest.
WAIVED: dict[str, str] = {
    "schema_version": "version stamp — internal, not prose",
    "taxonomy_version": "version stamp — internal, not prose",
    "scoredAt": "timestamp — internal, not prose",
    "verification": "verification metadata — internal, not prose",
    "dataCompleteness": "coverage metadata — confidence is shown in the header",
    "intent_score": "internal sub-score — rolled into composite + dimensions",
    "compositeLabel": "word-label for composite — the composite number is rendered",
    "dominantMode": "rendered via the Work modes section (workMode.dominant)",
    "titles": "earned-flags array — the Kinds section renders titlesCatalog",
    "map": "x/y coordinates for the 2D positioning visual — positioning is rendered narratively",
    "activityByDay": "per-day heatmap array — the Activity section summarizes it",
    "stack": "manual stack list — the scanned stackSummary is rendered instead",
}


def _nonempty(v) -> bool:
    return v not in (None, "", [], {})


def _referenced(key: str) -> bool:
    # Rendered fields are accessed by quoted literal, e.g. profile.get("harness").
    # The quotes disambiguate substrings ("titles" vs "titlesCatalog").
    return f'"{key}"' in MD_SOURCE


def test_every_shareable_field_is_curated_or_waived():
    shareable = build_shareable_profile(EXAMPLE, {})
    uncovered = [
        k for k, v in shareable.items() if _nonempty(v) and not _referenced(k) and k not in WAIVED
    ]
    assert not uncovered, (
        f"shareable fields neither rendered in markdown_export.py nor waived: {uncovered} — "
        "render them (add a curated section) or add to WAIVED here with a reason. "
        "This is the guard that keeps profile.md/report.md from silently dropping fields."
    )


def test_waived_fields_are_real_and_not_secretly_rendered():
    # A waiver for a field that IS rendered, or that no longer exists, is stale.
    shareable = build_shareable_profile(EXAMPLE, {})
    for k, reason in WAIVED.items():
        assert reason, f"WAIVED[{k}] needs a reason"
        if k in shareable and _referenced(k):
            raise AssertionError(
                f"{k} is waived but IS rendered in markdown_export.py — drop it from WAIVED"
            )


def test_every_number_metric_has_a_glossary_entry():
    # "Your numbers" mirrors profile.js card copy; every metric the md collects
    # must carry its what-it-means/how-measured glossary, or the report view
    # would print a number with an empty explanation.
    ids = {n["id"] for n in _collect_numbers(EXAMPLE)}
    missing = ids - set(_GLOSSARY)
    assert not missing, f"'Your numbers' metrics with no _GLOSSARY entry: {missing}"


def test_enrichment_six_block_contract_is_rendered():
    # The enrichment blocks are a frozen contract; the report must render each
    # (growthAreas is private and dropped from shareable, but still rendered
    # when present locally). If a block stops being referenced, this goes red.
    blocks = [
        "narrative",
        "positioningLine",
        "whatYouBuilt",
        "decisionPatterns",
        "strengths",
        "growthAreas",
        "howYouUseAI",
    ]
    missing = [b for b in blocks if f'"{b}"' not in MD_SOURCE]
    assert not missing, f"enrichment blocks not rendered in markdown_export.py: {missing}"


def test_curated_additions_actually_appear_in_output():
    # End-to-end: the fields we just curated must show up in the rendered report
    # for the example (guards against a helper that's defined but never wired in).
    rep = profile_to_markdown(EXAMPLE, "report")
    assert "## Stack & tooling" in rep
    assert "Anthropic SDK" in rep  # stackSummary frameworks
    assert "primary —" in rep  # modelsSummary
    assert markdown_export._prettify  # module imported, sanity


# ── HTML surface ──────────────────────────────────────────────────────────────
# The views read the raw JSON off one of these roots: `api`/`data` (raw parse),
# `P`/`_P` (profile.js's Object.assign-derived view object), `_RAW`/
# `_reportData` (the globals). A field rendered by a view is read off one of
# them by name at least once; root-anchoring is what lets us tell `api.map`
# (a field read) apart from `arr.map(...)` (an array method — 68 of those).
VIEW_JS_FILES = ("profile.js", "report.js", "tabs-shared.js")
JS_SOURCE = "\n".join(
    (ROOT / "nextmillionai" / "static" / "js" / f).read_text() for f in VIEW_JS_FILES
)
_JS_ROOTS = ("api", "data", "P", "_P", "_RAW", "_reportData")

# Full-profile top-level fields no view reads, each with a reason. Three of
# these (map, growthEdge, trajectory) are substantive fields the engine
# computes that NO surface currently renders — flagged for review, not dead-code
# removal (touching the schema is a hardline).
HTML_WAIVED: dict[str, str] = {
    "schema_version": "version stamp — internal",
    "taxonomy_version": "version stamp — internal",
    "scoredAt": "timestamp — internal",
    "verification": "verification metadata — internal",
    "dataCompleteness": "completeness metadata — internal",
    "compositeLabel": "word-label for composite — the composite number is rendered",
    "dominantMode": "denormalized copy of workMode.dominant — workMode is rendered",
    "titles": "earned-flags array — the views render titlesCatalog",
    "map": "2D positioning coordinates — read by no view (positioning.* renders); review candidate",
    "growthEdge": "private growth-edge — computed but surfaced by no view; review candidate",
    "trajectory": "private trajectory — computed but surfaced by no view; review candidate",
    "avatar": "served via /api/avatar (demo profile carries it); fetched, not read off P",
}


def _consumed_by_view(field: str) -> bool:
    f = re.escape(field)
    for r in _JS_ROOTS:
        rr = re.escape(r)
        # <root>.field  (dot)  or  <root>["field"] / ['field']  (bracket)
        if re.search(rf"(?<![\w$]){rr}\s*\.\s*{f}\b", JS_SOURCE):
            return True
        if re.search(rf"(?<![\w$]){rr}\s*\[\s*['\"]{f}['\"]", JS_SOURCE):
            return True
    return False


def test_every_profile_field_is_consumed_by_a_view_or_waived():
    # The HTML equivalent of the md coverage guard, over the FULL profile (the
    # views render everything locally). A field the engine emits that no view
    # reads turns this red and names it.
    uncovered = [
        k
        for k, v in EXAMPLE.items()
        if _nonempty(v) and not _consumed_by_view(k) and k not in HTML_WAIVED
    ]
    assert not uncovered, (
        f"profile fields read by NO view (profile.js/report.js/tabs-shared.js) "
        f"and not waived: {uncovered} — render them in a view, or add to HTML_WAIVED "
        "with a reason. Keeps the HTML views from silently dropping a field."
    )


def test_html_waived_fields_are_real_and_not_secretly_consumed():
    # A waiver for a field that IS consumed by a view is stale — drop it.
    for k, reason in HTML_WAIVED.items():
        assert reason, f"HTML_WAIVED[{k}] needs a reason"
        if k in EXAMPLE and _consumed_by_view(k):
            raise AssertionError(
                f"{k} is HTML-waived but IS read by a view — drop it from HTML_WAIVED"
            )


def test_key_orchestration_fields_are_read_by_a_view():
    # The exact fields that drifted out of the md; pin their HTML presence so a
    # refactor that drops one is loud (belt-and-suspenders over the scan above).
    for f in ("harness", "leverage", "archetypes", "businessFit", "wrappedStats", "signals"):
        assert _consumed_by_view(f), f"{f} is no longer read by any view"
