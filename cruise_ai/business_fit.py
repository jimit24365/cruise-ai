"""
cruise_ai.business_fit -- Business Fit Map (report-only rendering).

Positions a builder in a 2D landscape of AI business segments and scores
fit-to-segment. Fit percentages are FIT-TO-CONTEXT — the same output
class as role comparison — never builder-vs-builder ranking. See
docs/BUSINESS-FIT-MAP.md for placement, framing, and naming policy.

Signal chain (every number must trace through it):
  local sessions+git -> normalized metrics -> dimensions -> archetype
  scores -> map position + zone affinity

Naming policy: zones carry CATEGORY examples only — never company names.

v1 amendment over the legacy spec: `multi_agent_orchestrator` (added to
the taxonomy after the original formulas) contributes to the AI-native
axis signal and to the Autonomous Agents zone requirements; weights were
rebalanced to keep each signal's weight sum at 1.0.
"""

from __future__ import annotations

# ── Zone definitions (categories only — no company names) ───────────────────

BUSINESS_ZONES: list[dict] = [
    {
        "id": "dev_tools",
        "name": "AI Developer Tools",
        "x": 0.3,
        "y": -0.4,
        "radiusX": 0.20,
        "radiusY": 0.18,
        "color": "#3F6CC7",
        "categories": ["IDE copilots", "code assistants", "dev environments"],
        "fitRequirements": [
            {"archetypeId": "agent_builder", "minScore": 85, "weight": 0.35},
            {"archetypeId": "rapid_prototyper", "minScore": 80, "weight": 0.25},
            {"archetypeId": "context_engineer", "minScore": 70, "weight": 0.20},
            {"archetypeId": "code_weaver", "minScore": 60, "weight": 0.20},
        ],
        "description": "Building AI-powered tools that make developers more productive",
    },
    {
        "id": "autonomous_agents",
        "name": "Autonomous Agents",
        "x": 0.7,
        "y": 0.0,
        "radiusX": 0.18,
        "radiusY": 0.20,
        "color": "#7C5BD6",
        "categories": ["agent orchestration", "multi-agent frameworks", "MCP tooling"],
        "fitRequirements": [
            {"archetypeId": "agent_builder", "minScore": 85, "weight": 0.30},
            {"archetypeId": "multi_agent_orchestrator", "minScore": 65, "weight": 0.15},
            {"archetypeId": "integration_architect", "minScore": 75, "weight": 0.25},
            {"archetypeId": "system_thinker", "minScore": 70, "weight": 0.15},
            {"archetypeId": "context_engineer", "minScore": 60, "weight": 0.15},
        ],
        "description": "Multi-agent orchestration and autonomous AI systems",
    },
    {
        "id": "vertical_ai",
        "name": "Vertical AI SaaS",
        "x": 0.2,
        "y": 0.4,
        "radiusX": 0.22,
        "radiusY": 0.18,
        "color": "#1F9254",
        "categories": ["legal workflow AI", "healthcare AI", "finance automation"],
        "fitRequirements": [
            {"archetypeId": "code_weaver", "minScore": 80, "weight": 0.35},
            {"archetypeId": "automation_engineer", "minScore": 70, "weight": 0.25},
            {"archetypeId": "integration_architect", "minScore": 70, "weight": 0.25},
            {"archetypeId": "system_thinker", "minScore": 60, "weight": 0.15},
        ],
        "description": "AI applied to healthcare, legal, finance — regulated domains",
    },
    {
        "id": "ai_infra",
        "name": "AI Infrastructure",
        "x": 0.6,
        "y": 0.5,
        "radiusX": 0.16,
        "radiusY": 0.14,
        "color": "#CB5A45",
        "categories": ["foundation models", "inference platforms", "model serving"],
        "fitRequirements": [
            {"archetypeId": "system_thinker", "minScore": 85, "weight": 0.30},
            {"archetypeId": "agent_builder", "minScore": 80, "weight": 0.30},
            {"archetypeId": "automation_engineer", "minScore": 75, "weight": 0.25},
            {"archetypeId": "code_weaver", "minScore": 70, "weight": 0.15},
        ],
        "description": "Foundation models, inference platforms, core AI infrastructure",
    },
    {
        "id": "ai_enterprise",
        "name": "AI-Augmented Enterprise",
        "x": -0.3,
        "y": 0.3,
        "radiusX": 0.22,
        "radiusY": 0.18,
        "color": "#CF8A1A",
        "categories": ["enterprise SaaS AI", "workplace productivity", "integration layers"],
        "fitRequirements": [
            {"archetypeId": "integration_architect", "minScore": 80, "weight": 0.35},
            {"archetypeId": "code_weaver", "minScore": 70, "weight": 0.25},
            {"archetypeId": "automation_engineer", "minScore": 65, "weight": 0.25},
            {"archetypeId": "system_thinker", "minScore": 60, "weight": 0.15},
        ],
        "description": "Adding AI capabilities to existing enterprise products",
    },
    {
        "id": "ai_startups",
        "name": "AI-First Startups",
        "x": -0.2,
        "y": -0.5,
        "radiusX": 0.22,
        "radiusY": 0.16,
        "color": "#E2542C",
        "categories": ["seed-stage builders", "indie AI products", "rapid MVP shops"],
        "fitRequirements": [
            {"archetypeId": "rapid_prototyper", "minScore": 85, "weight": 0.35},
            {"archetypeId": "agent_builder", "minScore": 70, "weight": 0.30},
            {"archetypeId": "cli_native", "minScore": 50, "weight": 0.20},
            {"archetypeId": "context_engineer", "minScore": 50, "weight": 0.15},
        ],
        "description": "Early-stage companies shipping fast with AI leverage",
    },
    {
        "id": "ai_security",
        "name": "AI Security & Safety",
        "x": 0.0,
        "y": 0.7,
        "radiusX": 0.15,
        "radiusY": 0.12,
        "color": "#B5485D",
        "categories": ["AI safety", "red teaming", "compliance tooling"],
        "fitRequirements": [
            {"archetypeId": "code_weaver", "minScore": 85, "weight": 0.35},
            {"archetypeId": "automation_engineer", "minScore": 80, "weight": 0.30},
            {"archetypeId": "system_thinker", "minScore": 75, "weight": 0.25},
            {"archetypeId": "context_engineer", "minScore": 60, "weight": 0.10},
        ],
        "description": "AI safety, security testing, and compliance systems",
    },
    {
        "id": "ai_consumer",
        "name": "AI Consumer Products",
        "x": -0.5,
        "y": -0.3,
        "radiusX": 0.16,
        "radiusY": 0.14,
        "color": "#8A5BC7",
        "categories": ["consumer chatbots", "AI search", "companion apps"],
        "fitRequirements": [
            {"archetypeId": "rapid_prototyper", "minScore": 80, "weight": 0.35},
            {"archetypeId": "context_engineer", "minScore": 70, "weight": 0.25},
            {"archetypeId": "integration_architect", "minScore": 65, "weight": 0.25},
            {"archetypeId": "code_weaver", "minScore": 55, "weight": 0.15},
        ],
        "description": "Consumer-facing AI products — chatbots, search, companions",
    },
]


def _score(archetypes: list[dict], archetype_id: str) -> float:
    for a in archetypes or []:
        if a.get("id") == archetype_id:
            return float(a.get("score") or 0)
    return 0.0


def compute_map_position(archetypes: list[dict]) -> dict:
    """Archetype-weighted axes, each normalized to -1..+1.

    X: AI-Augmented (-1) <-> AI-Native (+1)
    Y: Velocity (-1)     <-> Precision (+1)

    multi_agent_orchestrator joins buildingSignal (it is the most
    AI-native signal in the taxonomy); agent_builder's weight was
    rebalanced .35 -> .25 to keep the sum at 1.0.
    """
    g = lambda i: _score(archetypes, i)  # noqa: E731

    building = (
        g("agent_builder") * 0.25
        + g("multi_agent_orchestrator") * 0.10
        + g("integration_architect") * 0.25
        + g("context_engineer") * 0.20
        + g("system_thinker") * 0.20
    )
    using = (
        g("rapid_prototyper") * 0.30
        + g("code_weaver") * 0.25
        + g("automation_engineer") * 0.25
        + g("cli_native") * 0.20
    )
    precision = (
        g("code_weaver") * 0.35
        + g("automation_engineer") * 0.30
        + g("system_thinker") * 0.20
        + g("context_engineer") * 0.15
    )
    velocity = g("rapid_prototyper") * 0.40 + g("agent_builder") * 0.30 + g("cli_native") * 0.30

    return {
        "x": round((building - using) / 100, 3),
        "y": round((precision - velocity) / 100, 3),
    }


def compute_zone_affinity(archetypes: list[dict], zone: dict) -> dict:
    """Fit-to-segment: weighted closeness to each requirement, capped at
    100% per requirement. Strong fit = every minimum met."""
    total_score = 0.0
    total_weight = 0.0
    gaps: list[dict] = []
    for req in zone["fitRequirements"]:
        score = _score(archetypes, req["archetypeId"])
        total_score += min(score / req["minScore"], 1.0) * req["weight"] * 100
        total_weight += req["weight"]
        if score < req["minScore"]:
            gaps.append(
                {
                    "archetypeId": req["archetypeId"],
                    "required": req["minScore"],
                    "actual": round(score),
                }
            )
    return {
        "percentage": round(total_score / total_weight) if total_weight else 0,
        "gaps": gaps,
        "isStrongFit": not gaps,
    }


def build_business_fit(archetypes: list[dict]) -> dict | None:
    """Full Business Fit Map data for the report. None if no archetypes
    are scored (insufficient data beats a fabricated map)."""
    if not archetypes or all((a.get("score") or 0) == 0 for a in archetypes):
        return None

    position = compute_map_position(archetypes)
    zones = []
    for zone in BUSINESS_ZONES:
        affinity = compute_zone_affinity(archetypes, zone)
        zones.append(
            {
                "id": zone["id"],
                "name": zone["name"],
                "x": zone["x"],
                "y": zone["y"],
                "radiusX": zone["radiusX"],
                "radiusY": zone["radiusY"],
                "color": zone["color"],
                "categories": zone["categories"],
                "description": zone["description"],
                "requirements": [
                    {
                        "archetypeId": r["archetypeId"],
                        "minScore": r["minScore"],
                        "weight": r["weight"],
                        "actual": round(_score(archetypes, r["archetypeId"])),
                    }
                    for r in zone["fitRequirements"]
                ],
                "affinity": affinity["percentage"],
                "gaps": affinity["gaps"],
                "isStrongFit": affinity["isStrongFit"],
            }
        )
    zones.sort(key=lambda z: -z["affinity"])

    return {
        "position": position,
        "axes": {
            "x": ["AI-Augmented", "AI-Native"],
            "y": ["Velocity", "Precision"],
        },
        "zones": zones,
        "topFits": [
            {"id": z["id"], "name": z["name"], "affinity": z["affinity"]} for z in zones[:3]
        ],
        "framing": (
            "Fit-to-segment, not a ranking. Scores compare your archetype "
            "profile to segment requirements derived from your local "
            "sessions + git — never to other builders."
        ),
    }
