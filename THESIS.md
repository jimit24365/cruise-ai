# cruise_ai — Why We Measure What We Measure

The thesis behind the scoring, and the outside evidence behind the thesis. This
document exists so the taxonomy doesn't read as our own invention — every claim
below is anchored to independent research, cited at the end. Where the evidence
is mixed or limited, we say so.

---

## The thesis in one paragraph

AI changed how software gets built. But **whether you use AI is no longer the
signal — how you build with it is.** Two engineers with the same tools and the
same résumé produce wildly different outcomes: one ships fast and safe, one ships
fast and fragile. The market already pays for the difference, yet nothing makes it
visible — it's locked inside the IDE. cruise_ai reads the work you've already
done and makes the *how* legible, measured from observed behavior rather than
self-report.

Three findings hold this up.

---

## 1. Using AI is not the same as being good with AI

The most rigorous study to date found AI tools did **not** automatically make
skilled developers faster. In a randomized controlled trial, 16 experienced
open-source developers worked 246 real tasks in their own large repositories;
when allowed to use early-2025 AI tools (mainly Cursor + Claude), they took **19%
longer** — even though they predicted a 24% speedup and *still believed* AI had
sped them up afterward (METR, July 2025). METR has since revised the experiment
for later-2025 tools, so treat this as a snapshot, not a verdict — but the core
lesson is durable: **outcomes depend on the operator, not the tool.**

Larger studies sharpen rather than soften this. A peer-reviewed analysis of
three randomized field experiments with 4,867 developers found AI raised
completed tasks by ~26%, with the biggest gains among less-experienced
developers (Cui et al., 2025) — real value, but uneven and
operator-dependent. Ongoing Stanford research across 100,000+ developers
finds the other tail: raw output gains shrink once rework is counted, and
can turn negative in complex, mature codebases (Denisov-Blanch et al.,
2025, talk-based). Across the slowdown, the uplift, and the rework paradox,
the constant holds: outcomes track the operator and the context, not the
tool.

→ This is why cruise_ai scores **Signal Clarity** (how precisely you direct),
**Recovery Velocity** (how you handle wrong output), and **work mode** (how you
build) — not "do you use AI." Adoption is table stakes; the craft is the signal.

## 2. AI output needs human judgment to be safe and to survive

Functional ≠ sound. Veracode's 2025 GenAI Code Security Report ran 80+ tasks
across 100+ models and found AI-generated code introduced security
vulnerabilities (OWASP Top 10 class) in **45% of cases** — and, tellingly, newer
and larger models did **not** improve it, suggesting a structural problem, not a
temporary one (Veracode, 2025). Veracode sells security tooling, so read it with
that interest in mind — but the scale and methodology are hard to wave away, and
independent reporting echoes the pattern (more AI-assisted commits → more to
review). The shift to "vibe coding," where security constraints go unspecified,
hands those decisions to the model. Google's 2024 DORA report echoes the
cost at the team level: as AI adoption rose, respondents reported an
estimated 7.2% drop in delivery stability and 1.5% drop in throughput, and
39% said they had little or no trust in AI-generated code (DORA, 2024).

→ This is why cruise_ai scores **Build Stability** (does your AI-assisted code
survive — churn, reverts), and why **Production Guardian** is a first-class
archetype and **Security Instinct** is on the roadmap. The builders who catch what
the model misses are doing the highest-value work.

## 3. The skill has real, growing economic value — and it's invisible to hiring

Across ~1 billion job ads, PwC's 2025 Global AI Jobs Barometer found workers with
AI skills command a **56% wage premium** over peers in the same role — more than
double the **25%** premium a year earlier. AI-skill roles kept **growing 7.5%**
even as total postings fell **11.3%**, and the skills employers ask for are
changing **66% faster** in AI-exposed jobs (PwC, 2025). The value is real and
rising. The problem: the evidence for *who actually has the skill* lives inside
people's editors, where no résumé, LinkedIn, or interview can see it.

→ This is the gap cruise_ai fills: a profile built from observed work, so the
premium-worthy skill is finally provable — by you, to you first, and (later, on
your terms) to others.

---

## Why each dimension is on the list

| Dimension | Why it's worth measuring | Grounding |
|-----------|--------------------------|-----------|
| **Signal Clarity** | The operator, not the tool, drives outcomes; precise direction is the throughput bottleneck | METR (operator effect); PwC (prompt/AI skill premium) |
| **Build Stability** | AI code is often insecure/fragile; survival in production is the real test | Veracode (45% vulnerable); industry churn reports |
| **Recovery Velocity** | A large share of AI output is "almost right," so debugging AI output is now a core skill | METR (rework/slowdown); developer-survey rework signals |
| **Decision Weight** | AI makes generating code cheap; judgment about *what* to build is the scarce input | craft logic + architecture-decision research (less externally quantified — flagged) |
| **Context Command** | Context loss across tools/sessions is a top productivity drain; managing it compounds | craft logic + emerging context-engineering practice (less externally quantified — flagged) |
| **Orchestration Range** | Building has gone multi-tool, multi-model, multi-agent; coordination is the new frontier skill | rising agentic/MCP adoption (directional) |

We're explicit about which dimensions have hard external backing (1–3 above:
Signal Clarity, Build Stability, Recovery Velocity) and which rest more on craft
reasoning and emerging practice (Decision Weight, Context Command, Orchestration
Range). The latter are still scored, but they're the first candidates for
revision as better evidence arrives — which is the point of keeping the taxonomy
living.

---

## What we deliberately do NOT claim

- We do **not** claim a single number predicts job performance. Scores describe
  observed patterns; they are not a certified predictor.
- We do **not** claim the research is settled. METR is one snapshot (and was
  revised); Veracode is a vendor; PwC measures correlation in job ads. We cite
  them because they're the best available, not because they're the last word.
- We do **not** rank builder types against each other (see SCORING-METHODOLOGY).
- We do **not** measure "did you use AI" — only how you work when you do.
- We do **not** claim these scores apply outside their calibration. They are built
  and validated for people who **build software with AI** — developers and AI
  engineers — from coding-tool and git signals; we do not (yet) claim them for
  no-code, design, product, or research workflows. That's a *not yet*, not a verdict.

Honesty about the limits is part of the credibility. The taxonomy improves as the
evidence does.

---

## References

- **METR (2025).** *Measuring the Impact of Early-2025 AI on Experienced
  Open-Source Developer Productivity.* RCT; 16 developers, 246 tasks; 19% slowdown
  with AI. metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study ·
  arXiv:2507.09089. Update (Feb 2026): metr.org/blog/2026-02-24-uplift-update
- **Veracode (2025).** *2025 GenAI Code Security Report.* 100+ LLMs, 80+ tasks;
  45% of AI-generated code introduced OWASP-class vulnerabilities; no improvement
  with model scale. veracode.com/resources/analyst-reports/2025-genai-code-security-report
- **PwC (2025).** *Global AI Jobs Barometer.* ~1B job ads; 56% AI-skills wage
  premium (up from 25%); AI-skill roles +7.5% as total postings −11.3%; skills
  changing 66% faster in AI-exposed jobs. pwc.com/gx/en/services/ai/ai-jobs-barometer
- **Cui, Demirer, Jaffe, Musolff, Peng, Salz (2025).** *The Effects of
  Generative AI on High-Skilled Work: Evidence from Three Field Experiments
  with Software Developers.* Management Science; three RCTs, 4,867
  developers; +26% completed tasks, largest gains for less-experienced
  developers. papers.ssrn.com/sol3/papers.cfm?abstract_id=4945566
- **Google / DORA (2024).** *Accelerate State of DevOps Report.* AI
  adoption rose alongside an estimated 7.2% drop in delivery stability and
  1.5% drop in throughput; 39% reported little or no trust in AI-generated
  code. dora.dev/research/2024/dora-report
- **Denisov-Blanch et al. (2025).** Ongoing Stanford productivity research
  (100k+ developers) — the rework paradox; commit/PR counts mismeasure
  outcomes. softwareengineeringproductivity.stanford.edu *(talk-based; not
  yet peer-reviewed).*
- **Supporting / directional:** 2025 Stack Overflow Developer Survey (AI output
  "almost right, but not quite"; time spent debugging AI code); Apiiro (AI-assisted
  developers produce several times more commits → more to review). Used as context,
  not load-bearing claims.

Measurement-methodology citations (construct validity, holistic evaluation,
agentic-benchmark rigor — Raji 2021, HELM 2022, the Agentic Benchmark
Checklist 2025, SWE-bench, METR long-tasks) live in
[`docs/REFERENCES.md`](docs/REFERENCES.md).

*Document version 0.2 · 2026-06 · update as evidence evolves.*
