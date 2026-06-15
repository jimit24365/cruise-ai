# Builder Positioning Model — finalized concept

A value-neutral **map** of where a builder sits, layered on top of the existing
quality scores. The scores say *how well* you build with AI; this says *where you
are and what you build*. Concept only — no code yet.

---

## 0. The shift it captures (why now)

The frontier moved off prompt quality. Steinberger (Jun 2026): you shouldn't be
prompting agents, you should design the loops that prompt them. Boris Cherny (head
of Claude Code): "I don't prompt Claude anymore." Addy Osmani's "Loop Engineering":
the loop sits above the harness, driven by a state file on disk that survives runs.
And the growth reality: the jump from "write me a function" to "design the loop
that writes the functions" is where most people stall for months.

So the real differentiator among AI devs is no longer who writes good prompts. It's
**how much leverage you operate at** and **what you're building**. We turn that into
a map — not a score.

## 1. Core principle: a MAP, not a ladder

No region is "above" another. A brilliant Swift product engineer who prompts
directly is not below someone orchestrating ten agents — they're in different
places doing different work. The model reports **where your signals place you** and
**the nearest optional expansion**, fit-gated and honest. Never "level up," never
"you're behind." This is both your stated wish and our inclusivity rule.

## 2. Axis 1 — Leverage mode (HOW you build with AI)

The loops progression, as observed signal (not skill rank):

- **Prompting** — you direct the agent turn by turn. Single-shot or iterative.
- **Harnessing** — you build scaffolding around the agent: CLAUDE.md/rules, MCPs,
  hooks, tools, persistent context.
- **Looping** — you design a loop that prompts the agent for you: a state file on
  disk, self-feeding runs, scheduled/unattended execution.
- **Orchestrating** — you coordinate multiple agents/loops as the head: an
  orchestrator delegating to workers (OpenClaw / Gas Town style).

**v1 ships THREE stages** (decision): Prompting → Harnessing → **Designs the loop**.
"Orchestrating / multi-agent" is recognized as a **sub-flavor inside "Designs the
loop"** (a you-are-here detail), not a separate top tier yet — so the conductor is
acknowledged without turning the map into a 4-rung ladder.

Honest framing, always attached:
- Higher leverage is **fit, not better**. It pays off on **decomposable, repeatable**
  work (audits, reviews, test sweeps) and is weaker on tightly-coupled feature code.
- It costs ~15× the tokens of a chat. Worth it only when the work parallelizes.
- Staying at "prompting" can be the correct choice for the work in front of you.

## 3. Axis 2 — Build domain (WHAT you build)

- **AI systems** — you build the AI itself: agents, harnesses, multi-agent infra.
- **AI-powered products** — products with AI integrated (LLM features, API calls).
- **General products / software** — products where AI is your build tool, not the
  product.

Also a region, not a rank. Building a payments product is not lesser than building
an agent framework.

## 4. Tech-domain tag (WHERE you operate)

Detected from deps + files: e.g. TypeScript/React, Swift/iOS, Java/Spring,
Python/ML, Go, Rust. Reported as primary domain + breadth. Pure signal — no
language or stack ranked above another.

## 5. Your three dev types, mapped (they're regions, not tiers)

- **Type 1 — AI-systems builder:** build-domain = AI systems (harnesses, agents,
  multi-agent). Often high leverage by nature of the work.
- **Type 2 — AI integrator:** build-domain = AI-powered products; leverage usually
  prompting/harnessing. Ships products with AI features.
- **Type 3 — The conductor:** leverage = orchestrating (the head of many
  coordinated agents), at any build-domain. Ships products by directing fleets.

The map holds all three without ordering them; a person can sit between regions or
move over time.

## 6. Signals update (what changes in our model)

Add a **`positioning`** layer above the existing style layer (archetypes/workMode):
- `positioning.leverageMode` : {current: prompting|harnessing|designs_the_loop,
  subFlavor?: orchestrating, evidence[], adjacent} — `current` is the v1 three-stage
  enum; "orchestrating" rides along as an optional subFlavor, NEVER a fourth value.
  `adjacent` = the nearest optional expansion, fit-gated.
- `positioning.buildDomain`  : {primary: ai-systems|ai-products|products, evidence[]}.
- `positioning.techDomains`  : [{name, weight, evidence[]}].
- Relabel/extend the existing `map`: x = build domain (Products ↔ AI-systems),
  y = leverage (Prompting ↔ Designs-the-loop). The old Explorer/Architect and
  Solo/Orchestrator labels are kept as **sub-labels** inside the new axes where
  they add nuance (e.g. Orchestrator as the far-end sub-label of the leverage axis).
  Decision: the map VISUAL is **report-only**; the profile carries buildDomain +
  techDomains as neutral tags, not the map.

Relationship to what we have: archetypes/workMode/titles stay as the **style** layer
(how you behave in a session). `positioning` is the **identity** layer (where you
sit). The six dimensions stay the **quality** layer (how well). Three clean layers.

Still measurement, no model needed for the figures — only enrichment narrates them.

## 7. How code intelligence computes it (experimental, local)

- **buildDomain** — scan deps/imports: agent frameworks (openclaw, langgraph,
  crewai, autogen) or LLM SDKs wired as infra → AI systems; an LLM SDK behind a
  product feature → AI products; none → products.
- **leverageMode** — from sessions + config: bare prompts → prompting; CLAUDE.md /
  MCP / hooks present → harnessing; a state file driving runs + scheduled/unattended
  execution (Osmani's five blocks) → designs_the_loop. Multiple coordinated agents
  set subFlavor=orchestrating INSIDE designs_the_loop (never a separate value).
- **techDomains** — from manifests + file extensions.

All local, metrics-only, no code stored.

## 8. How enrichment narrates it (YC-bar specificity)

"You're a TypeScript/React product builder operating mostly at the harnessing
level — CLAUDE.md rules and three MCPs wired in, but runs are still hand-driven.
Your audit/review work decomposes cleanly; the nearest expansion is a single loop
with a state file so those runs feed themselves." Named evidence, honest adjacent
move, never a rank.

## 9. Main profile vs experimental (the split — decided)

- **Main profile (reliable, value-neutral, share-worthy):** `buildDomain`,
  `leverageMode`, and `techDomains` as neutral identity TAGS (text/badges) — all
  shareable; they're credentials, not weaknesses.
- **Report-only (not on the profile, not shareable):** the leverage **map visual**
  (you-are-here dot + nearest-expansion arrow) and the progression.
- **Experimental (softer / needs code scan):** the "what you can improve toward
  Designs-the-loop" suggestion and automation-%. buildDomain detection runs via the
  code scan but, once it lands, its result is shown on the main profile as a tag.

## 10. Decisions (locked 2026-06-08)

1. **buildDomain → main profile** (shareable). It's a positive identity credential.
2. **Map relabelled** to build-domain × leverage; old Explorer/Architect &
   Solo/Orchestrator labels reused as sub-labels where they add nuance.
3. **Three leverage stages for v1** — Prompting → Harnessing → Designs-the-loop;
   orchestrating/multi-agent is a sub-flavor inside "Designs the loop".
4. **Progression shown as a "you are here" dot + a "nearest expansion" arrow, no
   numbering** — so it reads as a position on a map, never a tier list.
5. **Leverage map is report-only**; the profile shows buildDomain/leverageMode/
   techDomains as neutral tags, not the map.

### Map-visual spec (for the report)
A 2D field: x = Products ↔ AI-systems, y = Prompting ↔ Designs-the-loop. A single
filled dot = "you are here" (from computed positioning). A faint arrow points to the
nearest expansion the builder's work actually supports (fit-gated; absent if their
work doesn't decompose). No axis numbers, no rungs, no score — a location, plus the
honest "fit, not better / ~15× tokens / decomposable-only" caveat in the caption.
