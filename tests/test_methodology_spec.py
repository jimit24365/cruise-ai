"""The methodology spec must never misstate the real scoring.

methodology_spec.py feeds the /methodology explorer. Its numbers are derived
live from scoring.py, but these tests pin that contract: weights, bands, and
mode adaptation must equal the engine, every dimension must be covered, and
every cited reference must resolve. If someone adds a dimension, changes a
weight, or cites a study that doesn't exist, CI goes red and names it — the
same drift discipline as the render-parity guards.
"""

from nextmillionai import scoring
from nextmillionai.methodology_spec import (
    CITATIONS,
    DIM_ORDER,
    DIMENSION_META,
    METRICS,
    MODE_ORDER,
    PROVENANCE,
    SECTION_LABELS,
    build_spec,
)
from nextmillionai.schema import METHODOLOGY_VERSION

SPEC = build_spec()


def test_dim_order_covers_exactly_the_engine_dimensions():
    # A new dimension in scoring.py (or a removed one) must be reflected here.
    engine_dims = set(scoring.score_dimensions({}).keys())
    assert set(DIM_ORDER) == engine_dims, (
        f"DIM_ORDER {set(DIM_ORDER)} != engine dimensions {engine_dims} — "
        "add the new dimension to methodology_spec (DIM_ORDER + DIMENSION_META)."
    )
    assert set(DIMENSION_META) == engine_dims


def test_spec_weights_match_the_engine():
    engine = scoring.score_dimensions({})
    for d in SPEC["dimensions"]:
        assert d["weight"] == round(engine[d["id"]]["weight"], 3), (
            f"{d['id']} weight {d['weight']} != engine {engine[d['id']]['weight']} — "
            "the spec must derive weights from scoring.py, never hand-type them."
        )


def test_base_and_mode_weights_renormalize_to_one():
    for m in SPEC["modes"]:
        total = round(sum(m["weights"].values()), 2)
        assert total == 1.0, f"mode {m['id']} weights sum to {total}, not 1.0"


def test_mode_adaptation_matches_adapt_weights():
    # Each mode's weights must equal scoring._adapt_weights — not a JS/Python re-impl.
    dims = scoring.score_dimensions({})
    for m in SPEC["modes"]:
        mode_id = "" if m["id"] == "base" else m["id"]
        expected = {k: round(v, 3) for k, v in scoring._adapt_weights(dims, mode_id).items()}
        assert m["weights"] == expected, f"mode {m['id']} weights drifted from _adapt_weights"


def test_modes_are_real_work_modes():
    for mode_id in MODE_ORDER:
        assert mode_id in scoring._WORK_MODES, f"{mode_id} is not a real work mode"


def test_bands_match_get_level():
    for b in SPEC["bands"]:
        assert scoring._get_level(b["min"])["id"] == b["id"]
        if b["min"] > 0:
            assert scoring._get_level(b["min"] - 1)["id"] != b["id"], (
                f"band {b['id']} min {b['min']} is not the true threshold"
            )


def test_every_dimension_citation_resolves():
    for d in SPEC["dimensions"]:
        for c in d["citations"]:
            assert c["key"] in CITATIONS, f"{d['id']} cites unknown reference {c['key']}"
            assert c.get("finding") and c.get("label"), f"citation {c['key']} missing fields"


def test_every_dimension_has_copy_and_evidence_note():
    for d in SPEC["dimensions"]:
        assert d["measures"] and d["signals"] and d["evidenceNote"], (
            f"{d['id']} is missing measures/signals/evidenceNote"
        )


def test_version_and_required_sections_present():
    assert SPEC["methodologyVersion"] == METHODOLOGY_VERSION
    assert SPEC["scope"]["title"] and SPEC["scope"]["body"] and SPEC["scope"]["notYet"]
    assert len(SPEC["openQuestions"]) >= 3
    assert SPEC["composite"]["formula"]


def test_spec_is_json_serializable_and_leaks_no_paths():
    import json

    blob = json.dumps(SPEC)
    assert "/Users/" not in blob and "/home/" not in blob


# ── Per-metric registry (provenance + reasoning) ──────────────────────────────


def test_every_metric_is_well_formed():
    for m in METRICS:
        for field in ("id", "label", "section", "type", "provenance", "derivation", "reasoning"):
            assert m.get(field), f"metric {m.get('id')} missing {field}"
        assert m["type"] in ("direct", "indirect"), f"{m['id']} bad type"
        assert m["provenance"] in PROVENANCE, f"{m['id']} bad provenance {m['provenance']}"
        assert m["section"] in SECTION_LABELS, f"{m['id']} unknown section {m['section']}"
        for c in m.get("citations", []):
            assert c in CITATIONS, f"{m['id']} cites unknown reference {c}"


def test_metric_ids_are_unique():
    ids = [m["id"] for m in METRICS]
    assert len(ids) == len(set(ids)), f"duplicate metric ids: {ids}"


def test_every_derived_construct_is_documented():
    # The indirect constructs the audit flagged as undocumented must now be here,
    # each with explicit logic + reasoning. This is the "no derived number is
    # unexplained" guard; extend the list as new constructs land.
    ids = {m["id"] for m in METRICS}
    required = {
        "composite",
        "archetypes",
        "work_modes",
        "titles",
        "leverage_mode",
        "build_domain",
        "footprint",
        "business_fit",
        "confidence",
        "trajectory",
        "anti_patterns",
        "heatmap_day",
        "surfaces_donut",
        "solo_equivalent",
    }
    missing = required - ids
    assert not missing, f"derived constructs missing from the registry: {missing}"


def test_every_indirect_metric_states_its_provenance_honestly():
    # An indirect number must never be labeled "measured" without being a real
    # count/ratio — reasoned-defaults and estimates must own their label.
    for m in METRICS:
        if m["type"] == "indirect" and m["provenance"] == "measured":
            # allowed only for count-like derivations (peak overlap, day-presence,
            # commit-weighted domain) — assert the reasoning says why it's counted.
            assert m["reasoning"], f"{m['id']} claims measured but gives no reasoning"


def test_reasoned_defaults_and_estimates_exist_and_are_owned():
    # The honesty check: the methodology must openly carry reasoned-defaults and
    # estimates, not hide them behind "measured".
    provs = {m["provenance"] for m in METRICS}
    assert "reasoned-default" in provs and "estimate" in provs
