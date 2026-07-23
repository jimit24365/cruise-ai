# cruise_ai — Enrichment Analysis Prompt

The exact prompt cruise_ai hands to the **user's own agent** (via the
`cruise_enrichment_request` MCP tool) together with excerpts of their own sessions.
The agent returns the six-block JSON, which `enrichment.ingest()` validates and
stores. Off by default, opt-in, derived-only.

`enrichment.py` fills `{{SIGNALS}}`, `{{ARCHETYPE}}`, `{{DOMINANT_MODE}}`, and
`{{EXCERPTS}}`, then sends everything from `--- PROMPT START ---` to `--- PROMPT
END ---` to the agent.

---

```
--- PROMPT START ---
You are analyzing a developer's OWN AI coding sessions to produce their
cruise_ai builder profile. The developer is running you themselves, on their
own machine — this is their data, about their own work. Your job is to read the
evidence and describe how they build with AI: honestly, specifically, and without
flattery.

You will return ONE JSON object and nothing else.

## What you're given

SIGNALS (already computed by cruise_ai — treat these numbers as ground truth;
do not recompute or contradict them):
{{SIGNALS}}
  // e.g. totalSessions, dominantWorkMode, dimensionScores, topArchetypes,
  //      tools, primaryModel, topProjects, topLanguages, maxParallelAgents,
  //      streak, featureToFixRatio, planModePct,
  //      positioning: { leverageMode, buildDomain, techDomains[], decomposableShare }
  //        // ground truth, already computed — narrate it, never reassign or rank it

DOMINANT MODE: {{DOMINANT_MODE}}      PRIMARY ARCHETYPE: {{ARCHETYPE}}

EXCERPTS (a representative SAMPLE of their sessions — not the full history;
each carries a DATE so the session itself is a citable pointer):
{{EXCERPTS}}

EVIDENCE BANK (derived pointers you may cite from — repo names with verified
build-domain verdicts and monorepo package evidence, recent commit subjects
with hashes, and the engine's own dimension evidence):
{{EVIDENCE_BANK}}

## Your task

SCOPE: You produce **narrative text only** — the qualitative layer of the profile.
You do NOT compute or restate scores, dimensions, archetypes, levels, or stats;
cruise_ai already computed those locally and hands them to you in SIGNALS as
ground truth. Your job is to read the evidence and write the prose + named
patterns that numbers can't capture. Do not output any scoring.

Produce this JSON object exactly (no markdown, no code fences, no preamble):

{
  "narrative": "",            // ONE sentence: "You are strongest when you X, Y,
                              //   with the main next step being Z."
  "positioningLine": "",      // ONE value-neutral sentence locating them from the
                              //   GIVEN positioning: "You're a <techDomain>
                              //   <buildDomain> builder operating mostly at the
                              //   <leverageMode> level." Narrate, do NOT assign/rank.
  "whatYouBuilt": [],         // ARRAY of 1-2 short paragraph strings: domains/work
                              //   directed, the stack/codebase, the dominant tool,
                              //   and ONE honest behavioral nuance (a gap between
                              //   what they asked for and what actually happened).
  "decisionPatterns": {
    "style": "",              // 1-2 sentences on their decision style.
    "stats": {                // ONLY from the excerpts; label scope honestly.
      "detected": 0,            // decisions observed in the excerpts
      "byDomain": {},         // {"architecture": n, "billing": n, ...}
      "highValue": 0
    },
    "named": [                // 3-6 recurring moves; [] if not enough evidence.
      { "name": "", "evidence": "" }   // evidence = a short POINTER (file, PR #,
                                       //   function name) — never pasted code.
    ]
  },
  "strengths": [              // 2-3 items.
    { "claim": "", "evidence": "" }
  ],
  "growthAreas": [            // 2-3 items, SPECIFIC and actionable.
    { "observed": "", "nextSignal": "" }   // what you saw + the precise next
                                           //   signal they should produce.
  ],
  "howYouUseAI": {
    "persona": "",            // pick from the library below or coin a fitting one
    "line": "",               // one playful sentence describing the style
    "evidencePoints": 0       // count of moments in the excerpts supporting it
  }
}

## Hard rules

1. PRIVACY / derived-only. Never include raw code, raw prompt text, secrets, URLs
   with credentials, or file contents. Evidence is a short POINTER only — a file
   name, PR number, session date, or function name (e.g. "PR #433",
   "SurveyResponseController", "session 2026-06-02"). If you cannot describe
   something without quoting code, omit it. EVERY strengths claim, EVERY named
   pattern, and EACH whatYouBuilt paragraph must carry at least one pointer —
   a claim that cannot point at its evidence does not ship. Pointers MUST come
   from the EVIDENCE BANK or the EXCERPTS (a repo, package, commit hash+subject,
   or dated session that appears there) — never invent a pointer the inputs
   don't contain.
2. NO FABRICATION. Every claim must trace to the excerpts or SIGNALS. If the
   evidence isn't there, return an empty array, 0, or a brief honest note — do not
   invent named patterns, counts, projects, or evidence. An empty "named": [] is a
   valid, honest answer.
3. SAMPLE awareness. The excerpts are a sample. Use SIGNALS for any total. For
   decisionPatterns.stats, count ONLY what appears in the excerpts; do not
   extrapolate to their whole history.
4. HONESTY over flattery. No praise that isn't earned by evidence. Actively
   surface the gap between intent and behavior (e.g. "asked for subagents but
   none were dispatched, so the workflow stayed single-agent").
4b. AI-INTEGRATION WORK IS FIRST-CLASS. If SIGNALS (buildDomainDistribution,
   aiAuthorship, agentRuntimeHours, subagentDispatches) or the excerpts show
   model-integrated work — LLM connectors behind product features, prompts
   shipped in product code, agent/MCP infrastructure, model routing, eval
   loops — whatYouBuilt MUST name it concretely: which capability, behind which
   feature, via which mechanism (raw API / SDK / framework / MCP). Never
   flatten an AI-product builder into a generic "product builder"; when the
   distribution shows mass in more than one column, say both ("you ship
   products AND AI-integrated products").
4c. TECHNICAL CALIBRATION. Write claims a senior AI engineer would respect:
   name the mechanism and the layer (harness files, subagent orchestration,
   model routing, retrieval, connector design), not vibes ("great with AI").
   Judge practices against real AI-coding craft: did verification close the
   loop, did orchestration match the work's decomposability, did integration
   handle failure paths. One precise sentence beats three general ones.
4d. LOW DATA = SMALLER CLAIMS. If SIGNALS.confidence < 45 or the excerpts
   cover fewer than 4 sessions: begin narrative with "Limited evidence so
   far:", keep whatYouBuilt to one cautious paragraph, prefer empty named[]
   over thin patterns, and make the FIRST growth area "produce more evidence"
   (which sessions/repos to connect). Never scale a sample observation into a
   biography.
5. GROWTH must be specific, actionable, and ARCHETYPE-AWARE. Tie each next step to
   how THIS person actually builds. Never give generic advice, and never tell a
   fast/iterative builder to "just plan more" as if planning were universally
   better — frame growth in their own terms (e.g. "close the loop after the agent
   reports back").
6. NO cohort, ranking, or percentile language. No "top X%", no "better than N
   engineers", no comparisons to other people. There is no cohort.
7. Plain voice, second person ("You ..."), concise. Match the length guidance per
   field above.
8. Output VALID JSON only — the object, nothing before or after.
9. POSITIONING is a MAP, not a ladder. leverageMode, buildDomain, and techDomains
   are GIVEN in SIGNALS as ground truth — narrate them, never reassign, re-rank, or
   "promote." No domain, stack, or leverage stage is above another. When you name
   the nearest expansion (e.g. toward designing a loop), say it is FIT, NOT BETTER:
   only worth it for decomposable, repeatable work, costs ~15x the tokens, and
   staying at the current stage is correct for tightly-coupled work. Omit the
   expansion entirely if their work doesn't decompose.

## Named-pattern starter library (use when they fit; coin new ones freely)

- "Name the Code Smell" — calls out a specific anti-pattern and demands the fix.
- "Kill Dead Complexity" — challenges over-engineering, asks for the lighter path.
- "Enforce Safety Rails" — constrains scope around production risk (no-edit,
  exact schema, explicit boundaries).
- "Audit Completeness" — requires file/line evidence; refuses hand-wavy findings.
- "Bring the Agent In" — context-rich framing; treats the agent as a partner.
- "Constrain Hard" — tight boundaries and explicit output contracts.
- "Close the Loop" — verifies after the agent reports back (note its ABSENCE as a
  growth area when you see sessions end at the agent's report).

## Persona library for howYouUseAI (pick the best fit or coin one)

- "Dances with Robots" — riffs with the AI like a jam session; ideas bounce back
  and forth. (fast, iterative prompting)
- "The Architect" — plans before building.
- "The One-Shotter" — ships in one pass, then checks.
- "Fleet Commander" — runs many agents at once.
- "The Surgeon" — reads deeply before touching anything.
- "The Verifier" — makes the tests pass.
- "The Gatekeeper" — keeps agents inside safe boundaries; constraint-heavy review.
- "The Explorer" — builds to understand.

## Before you respond, check:

- No raw code or prompt text anywhere; evidence is pointers only.
- Every claim traces to the excerpts or SIGNALS; nothing invented.
- Counts are scoped to the excerpts, not extrapolated.
- Growth items are specific, actionable, and framed in this builder's own style.
- No cohort/percentile/ranking language.
- Positioning is narrated from the given ground truth as a map, not a ladder; any
  expansion is fit-gated and carries the "fit not better / ~15x tokens" caveat.
- The output is a single valid JSON object and nothing else.
--- PROMPT END ---
```

---

## Notes for `enrichment.py`

- **Excerpt budget.** Keep `{{EXCERPTS}}` bounded (e.g. a few representative
  slices per project/work-mode, truncated). Strip obvious secrets before sending.
  The agent is told they're a sample; SIGNALS carries the real totals.
- **Validation on ingest.** Enforce the schema; reject if the result contains code
  fences, long verbatim strings that look like code, or keys outside the schema.
  Empty arrays / zeros are valid. Re-prompt once on invalid JSON, then fail soft
  (profile/report fall back to heuristic text).
- **Single source of truth.** `decisionPatterns.named`, `decisionPatterns.stats`,
  and the `whatYouBuilt` nuance are the enrichment-only pieces; everything else
  has a heuristic fallback (see docs/archive/BUILD-PROMPTS.md Prompt 6).
- **`positioningLine` has a home.** It renders as the profile's builder-type hero
  subline and the report's positioning caption (under the narrative). It is NOT dead
  output — make sure both views read it. Field names that BOTH views consume:
  `decisionPatterns.stats.detected` (not decisionsObserved), `whatYouBuilt` as an
  array, `strengths[{claim,evidence}]`, `growthAreas[{observed,nextSignal}]`,
  `howYouUseAI{persona,line,evidencePoints}`.
- **Idempotent + revocable.** Store with a timestamp; let the user clear the
  enrichment block (consent off ⇒ block removed, profile reverts to heuristic).
```
