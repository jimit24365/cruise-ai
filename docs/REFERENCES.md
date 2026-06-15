# References

The formal bibliography behind nextmillionai's scoring. We wrote this
because a measurement product should be able to show its sources — the
taxonomy is meant to read as anchored work, not personal opinion. The
narrative *why* is [`THESIS.md`](../THESIS.md); this is the citation list
it draws on, plus the software-engineering and productivity research that
shaped the design.

**Honest framing (stated up front):** the three AI-specific studies in
"Load-bearing" are the strongest external backing, and they back three
dimensions (Signal Clarity, Build Stability, Recovery Velocity). The
"Design anchors" are established, widely-cited work that *informed* how we
think about measurement — they are not claims that any single paper
validates our exact bands. Bands are our research-derived calibration and
are recalibrated as real usage data accrues (per-user calibration is on
the post-launch roadmap). We do not claim the science is settled; we cite
the best available, not the last word.

## Load-bearing — AI-specific evidence

- **METR (2025).** *Measuring the Impact of Early-2025 AI on Experienced
  Open-Source Developer Productivity.* RCT; 16 developers, 246 real tasks;
  19% slowdown with AI despite developers predicting and perceiving a
  speedup. arXiv:2507.09089 ·
  metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study
  *(Feb 2026 update: metr.org/blog/2026-02-24-uplift-update).*
  **Grounds:** the operator — not the tool — drives outcomes → Signal
  Clarity, Recovery Velocity, work mode.
- **Veracode (2025).** *2025 GenAI Code Security Report.* 100+ LLMs, 80+
  tasks; ~45% of AI-generated code introduced OWASP-class
  vulnerabilities, with no improvement at larger model scale. Vendor
  report — read with that interest in mind.
  veracode.com/resources/analyst-reports/2025-genai-code-security-report
  **Grounds:** AI code needs human judgment to be safe and to survive →
  Build Stability; Production Guardian archetype; Security Instinct
  (roadmap).
- **PwC (2025).** *Global AI Jobs Barometer.* ~1B job ads; 56% wage
  premium for AI skills (up from 25%); AI-skill roles +7.5% as total
  postings −11.3%. Correlation in job ads, not causation.
  pwc.com/gx/en/services/ai/ai-jobs-barometer
  **Grounds:** the skill has real, rising value that hiring can't see →
  the whole premise of a proof-based profile.

## Design anchors — software-engineering & productivity research

These shaped *how* we measure, not the specific band cutoffs.

- **Forsgren, Storey, Maddila, Zimmermann, Houck, Butler (2021).** *The
  SPACE of Developer Productivity.* ACM Queue 19(1). **Grounds:** never
  reduce a developer to one number — measure across dimensions. Directly
  behind the six-dimension model and "no single score predicts
  performance."
- **Forsgren, Humble, Kim (2018).** *Accelerate: The Science of Lean
  Software and DevOps* (IT Revolution); DORA program. **Grounds:**
  outcome/stability and recovery as first-class signals → Build
  Stability, Recovery Velocity.
- **Nagappan & Ball (2005).** *Use of Relative Code Churn Measures to
  Predict System Defect Density.* ICSE '05. **Grounds:** churn is a
  defect signal → AI-line survival / Build Stability framing.
- **Newport (2016).** *Deep Work.* Grand Central Publishing.
  **Grounds:** sustained focus as a unit of real output → deep / marathon
  session metrics and the gap-based active-time estimator.
- **Csikszentmihalyi (1990).** *Flow: The Psychology of Optimal
  Experience.* Harper & Row. **Grounds:** uninterrupted engaged stretches
  as the meaningful measure of working time → active-time (≤30-min-gap)
  estimator rather than raw wall-clock.

## Directional / contextual

Used as context, not load-bearing claims:

- **Stack Overflow (2025).** *Developer Survey* — AI output "almost right,
  but not quite"; time spent debugging AI code. → Recovery Velocity.
- **Apiiro (2025).** AI-assisted developers produce several times more
  commits → more to review. → Build Stability review burden.

---

*Living document — updated as the evidence evolves. If you find a stronger
or contradicting source, open an issue; honesty about the limits is part
of the credibility.*
