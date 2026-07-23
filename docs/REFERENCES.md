# References

The formal bibliography behind cruise_ai's scoring. We wrote this
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
- **Cui, Demirer, Jaffe, Musolff, Peng, Salz (2025).** *The Effects of
  Generative AI on High-Skilled Work: Evidence from Three Field
  Experiments with Software Developers.* Management Science. Three RCTs,
  4,867 developers (Microsoft, Accenture, a Fortune 100 firm); **+26.08%
  completed tasks** (SE 10.3%), with the largest gains among
  less-experienced developers. Peer-reviewed, large-N.
  papers.ssrn.com/sol3/papers.cfm?abstract_id=4945566
  **Grounds:** the value is real but *uneven and operator-dependent* — not
  an automatic uplift → why *how* you build is the signal, not whether you
  use AI (Signal Clarity, work mode).
- **Google / DORA (2024).** *Accelerate State of DevOps Report 2024.* As
  AI adoption rose, respondents reported productivity gains but an
  estimated **−1.5% delivery throughput and −7.2% delivery stability**,
  and **39% had little or no trust in AI-generated code.** Large annual
  survey (Google Cloud), not a controlled trial.
  dora.dev/research/2024/dora-report
  **Grounds:** AI can raise output while *lowering* delivery stability →
  Build Stability, Recovery Velocity, and the human-judgment thesis.

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

## Evaluation & measurement methodology

cruise_ai is itself a measurement instrument, so its design is
disciplined by the science of evaluation — not as band validation, but as
the standard we hold our own methodology to (construct validity,
multi-dimensional scoring over a single number, resistance to gaming).
These also frame the open benchmark direction: long-horizon, agentic
coding evaluation.

- **Raji, Bender, Paullada, Denton, Hanna (2021).** *AI and the Everything
  in the Whole Wide World Benchmark.* NeurIPS Datasets & Benchmarks.
  **Grounds:** benchmarks routinely fail to measure what they claim
  (construct validity) → why every score ties to an explicit construct and
  unmeasured signals are marked *insufficient*, never estimated.
- **Liang, Bommasani, Lee, et al. (2022).** *Holistic Evaluation of
  Language Models (HELM).* Stanford CRFM; arXiv:2211.09110.
  **Grounds:** evaluate across many metrics and scenarios, never collapse
  to one number → the six-dimension model and "no single score predicts
  performance."
- **Zhu, Jin, Pruksachatkun, Kapoor, et al. (2025).** *Establishing Best
  Practices for Building Rigorous Agentic Benchmarks.* NeurIPS 2025
  Datasets & Benchmarks; arXiv:2507.02825. Introduces the Agentic
  Benchmark Checklist; task/reward-design flaws can misestimate agent
  performance by up to 100% relative (e.g. SWE-bench-Verified, tau-bench).
  **Grounds:** anti-gaming and outcome validity → arithmetic, auditable
  scoring and the agentic-eval direction.
- **Measuring What Matters: Construct Validity in LLM Benchmarks (2025).**
  arXiv:2511.04703. **Grounds:** supporting construct-validity argument
  for measurement design.
- **Jimenez, Yang, Wettig, Yao, Pei, Press, Narasimhan (2024).**
  *SWE-bench: Can Language Models Resolve Real-World GitHub Issues?* ICLR
  2024; arXiv:2310.06770. **Grounds:** the canonical *single-shot* code
  benchmark — the baseline a long-horizon, multi-turn behavioral benchmark
  is meant to go beyond.
- **METR (2025).** *Measuring AI Ability to Complete Long Tasks.*
  arXiv:2503.14499. Task-completion *time horizon* doubling ~every 7
  months. **Grounds:** long-horizon capability is where measurement is
  breaking → the long-session / Orchestration framing and the benchmark
  direction. (Distinct from the METR productivity RCT above.)

## Directional / contextual

Used as context, not load-bearing claims:

- **Stack Overflow (2025).** *Developer Survey* — AI output "almost right,
  but not quite"; time spent debugging AI code. → Recovery Velocity.
- **Apiiro (2025).** AI-assisted developers produce several times more
  commits → more to review. → Build Stability review burden.
- **Denisov-Blanch et al. (2025).** Ongoing Stanford software-engineering
  productivity research (100k+ developers, 600+ companies; presented in
  2025 talks, not yet a peer-reviewed paper). AI's raw output gains shrink
  after rework and can turn *negative* in complex, mature codebases and
  less-common languages; commit/PR counts mismeasure real productivity.
  softwareengineeringproductivity.stanford.edu → the rework paradox behind
  Build Stability and "counts aren't outcomes." *(Talk-based; cite as
  such.)*
- **Peng, Kalliamvakou, Cihon, Demirer (2023).** *The Impact of AI on
  Developer Productivity: Evidence from GitHub Copilot.* arXiv:2302.06590.
  55.8% faster on a constrained greenfield task — an upper bound on a
  narrow task, not whole-job productivity. → Signal Clarity context.

---

*Living document — updated as the evidence evolves. If you find a stronger
or contradicting source, open an issue; honesty about the limits is part
of the credibility.*
