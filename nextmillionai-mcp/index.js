#!/usr/bin/env node
/**
 * nextmillionai MCP server — your AI coding profile, as tools.
 *
 * Same engine as the CLI: every tool shells out to the nextmillionai
 * Python package or reads its local JSON. Fully local by default; the
 * only tool that sends anything anywhere is nma_publish, which is
 * explicitly gated and revocable.
 *
 * Install (Claude Code / Claude Desktop / Cursor MCP config):
 *   {
 *     "mcpServers": {
 *       "nextmillionai": {
 *         "command": "node",
 *         "args": ["/path/to/nextmillionai-mcp/index.js"]
 *       }
 *     }
 *   }
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';
import { execFile } from 'node:child_process';
import { readFile, writeFile, mkdtemp, rm, access } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { homedir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

// ─── Data directory: $NEXTMILLIONAI_HOME/data or ~/.nextmillionai/data ──────

const USER_HOME = process.env.NEXTMILLIONAI_HOME || join(homedir(), '.nextmillionai');
const DATA_DIR = join(USER_HOME, 'data');
const PROFILE_PATH = join(DATA_DIR, 'profile.json');
const DEFAULT_PORT = 7749;
const DEFAULT_REGISTRY = 'http://localhost:7750';
const EXPECTED_SCHEMA_VERSION = '1.0';

// Self-locating: this file lives at <repo>/nextmillionai-mcp/index.js, so the
// Python package is importable from <repo> even when nothing is pip-installed.
// The python fallbacks run with cwd=REPO_ROOT for exactly that reason.
const REPO_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));

// ─── Helpers ─────────────────────────────────────────────────────────────────

async function readProfile() {
  try {
    const raw = await readFile(PROFILE_PATH, 'utf-8');
    const profile = JSON.parse(raw);
    const v = profile.schema_version;
    if (v && v !== EXPECTED_SCHEMA_VERSION) {
      console.error(`[nextmillionai-mcp] Warning: profile schema_version=${v}, expected ${EXPECTED_SCHEMA_VERSION}`);
    }
    return profile;
  } catch (e) {
    if (e.code === 'ENOENT') return null;
    throw e;
  }
}

/** Run the nextmillionai CLI: `nextmillionai`, then python3/-m, then python/-m.
 * Python fallbacks run with cwd=REPO_ROOT so a bare clone works without
 * pip-installing the package — the install failure mode that bit real users. */
function runCLI(args = [], timeoutMs = 300_000) {
  const attempts = [
    ['nextmillionai', args, {}],
    ['python3', ['-m', 'nextmillionai', ...args], { cwd: REPO_ROOT }],
    ['python', ['-m', 'nextmillionai', ...args], { cwd: REPO_ROOT }],
  ];
  return new Promise((resolve, reject) => {
    const tryNext = (i) => {
      if (i >= attempts.length) {
        reject(new Error(
          'nextmillionai CLI not found. Tried: `nextmillionai` on PATH, then '
          + `\`python3 -m nextmillionai\` from ${REPO_ROOT}. `
          + 'Run the nma_doctor tool for a full diagnosis.'
        ));
        return;
      }
      const [cmd, cmdArgs, extra] = attempts[i];
      execFile(cmd, cmdArgs, { timeout: timeoutMs, env: { ...process.env }, ...extra },
        (err, stdout, stderr) => {
          if (!err) resolve(stdout + (stderr ? `\n${stderr}` : ''));
          else if (err.code === 'ENOENT') tryNext(i + 1);
          else if (i < attempts.length - 1 && /No module named/.test(stderr || '')) tryNext(i + 1);
          else reject(new Error(`nextmillionai failed: ${err.message}\n${stderr || stdout || ''}`));
        });
    };
    tryNext(0);
  });
}

/** Probe one command; resolve {ok, detail}. */
function probe(cmd, args, opts = {}) {
  return new Promise((resolve) => {
    execFile(cmd, args, { timeout: 15_000, env: { ...process.env }, ...opts },
      (err, stdout, stderr) => {
        if (!err) resolve({ ok: true, detail: (stdout || '').trim().split('\n')[0] });
        else resolve({ ok: false, detail: (stderr || err.message || '').trim().split('\n')[0] });
      });
  });
}

function dimScore(val) {
  if (typeof val === 'number') return val;
  if (val && typeof val === 'object' && typeof val.score === 'number') return val.score;
  return 0;
}

const titleCase = (s) => s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
const text = (t) => ({ content: [{ type: 'text', text: t }] });
const errText = (t) => ({ content: [{ type: 'text', text: t }], isError: true });

function profileSummary(profile) {
  const composite = profile.composite || profile.intent_score || 0;
  const dims = profile.dimensions || {};
  const archetypes = profile.archetypes || [];
  const primaryTitle = profile.primaryTitle || {};
  const assessment = profile.assessment || {};
  const positioning = profile.positioning || {};

  let out = `Composite: ${composite} (confidence ${assessment.confidence ?? '?'}%)\n`;
  out += `Sessions: ${assessment.sessions ?? '?'} | Range: ${assessment.dateRange || '?'} | Sources: ${(assessment.sources_used || []).join(', ')}\n\n`;

  out += 'Dimensions (measurements vs research-anchored bands — no percentiles):\n';
  for (const [key, val] of Object.entries(dims)) {
    out += `  ${titleCase(key)}: ${dimScore(val)}\n`;
  }

  const lev = positioning.leverageMode || {};
  const dom = positioning.buildDomain || {};
  if (lev.current) {
    out += `\nPositioning (a map, not a ladder — higher leverage is fit, not better):\n`;
    out += `  Leverage: ${lev.current}${lev.subFlavor ? ` (${lev.subFlavor})` : ''}\n`;
    out += `  Builds: ${dom.primary || '?'}\n`;
    const tech = (positioning.techDomains || []).slice(0, 5)
      .map((t) => `${t.name} ${t.weight}%`).join(', ');
    if (tech) out += `  Tech: ${tech}\n`;
  }

  if (archetypes.length > 0) {
    out += '\nTop archetypes:\n';
    for (const a of archetypes.slice(0, 5)) {
      out += `  ${a.icon || '?'} ${a.name}: ${a.score} (${a.level?.label || '-'})\n`;
    }
  }

  if (primaryTitle.name) {
    out += `\nPrimary title: ${primaryTitle.emoji || ''} ${primaryTitle.name}\n`;
  }
  return out;
}

// ─── MCP server ──────────────────────────────────────────────────────────────

const server = new McpServer({ name: 'nextmillionai', version: '0.2.0' });

// ── nma_doctor ───────────────────────────────────────────────────────────────

server.tool(
  'nma_doctor',
  `Diagnose the nextmillionai installation: is the engine reachable, which Python path works, does a profile exist, what to fix. Run this first if any other tool fails.`,
  {},
  async () => {
    const checks = [];

    const onPath = await probe('nextmillionai', ['--help']);
    checks.push(`[${onPath.ok ? 'ok' : '--'}] \`nextmillionai\` on PATH${onPath.ok ? '' : ' (fine if using the repo clone)'}`);

    const py = await probe('python3', ['-m', 'nextmillionai', '--help'], { cwd: REPO_ROOT });
    checks.push(`[${py.ok ? 'ok' : 'XX'}] \`python3 -m nextmillionai\` from ${REPO_ROOT}${py.ok ? '' : ` — ${py.detail}`}`);

    const pyVer = await probe('python3', ['--version']);
    checks.push(`[${pyVer.ok ? 'ok' : 'XX'}] ${pyVer.ok ? pyVer.detail + ' (3.9+ required)' : 'python3 not found'}`);

    let profileState = 'no profile yet — run nma_calibrate then nma_assess';
    try {
      await access(PROFILE_PATH);
      profileState = `profile present at ${PROFILE_PATH}`;
    } catch { /* absent */ }
    checks.push(`[..] ${profileState}`);
    checks.push(`[..] data home: ${USER_HOME} (override with NEXTMILLIONAI_HOME)`);
    checks.push(`[..] node ${process.version} (18+ required)`);

    const healthy = onPath.ok || py.ok;
    let out = `nextmillionai doctor\n${'='.repeat(40)}\n\n${checks.join('\n')}\n\n`;
    out += healthy
      ? 'Engine reachable — all tools should work.'
      : 'Engine NOT reachable. Fix: install Python 3.9+, then either `pip install -e .` from the repo, or keep the repo clone intact (this server runs `python3 -m nextmillionai` from it).';
    return text(out);
  }
);

// ── nma_calibrate ────────────────────────────────────────────────────────────

server.tool(
  'nma_calibrate',
  `Set up nextmillionai data collection: consent per source + collection scope.
Runs non-interactively with maximal defaults (all standard sources, all repos, all-time window). Experimental sources (Claude Desktop) stay OFF unless the user opts in interactively. Everything is read locally; nothing is uploaded.`,
  {},
  async () => {
    try {
      const out = await runCLI(['calibrate', '--yes']);
      return text(out.trim() + '\n\nConsent persisted. Run nma_assess next.');
    } catch (e) { return errText(`calibrate failed: ${e.message}`); }
  }
);

// ── nma_assess ───────────────────────────────────────────────────────────────

server.tool(
  'nma_assess',
  `Scan local AI coding sessions (Claude Code, Cursor, Codex, Kiro first-class, plus a wider field of editors, CLIs, and local model runtimes) + git and score the profile: six dimensions, archetypes, work modes, positioning, wrapped stats. Entirely local — no upload. Returns a structured summary plus the coverage report (what wasn't collected and the knob to widen it).`,
  {
    rescan: z.boolean().optional().describe('Force a fresh scan, ignoring cache.'),
    code: z.boolean().optional().describe('Opt-in local code scan: repo files reduced to metrics only (never stored, never sent).'),
    project: z.string().optional().describe('Scan a single project directory instead of all.'),
  },
  async ({ rescan, code, project }) => {
    try {
      const args = ['assess', '--yes'];
      if (rescan) args.push('--rescan');
      if (code) args.push('--code');
      if (project) args.push('--project', project);
      const out = await runCLI(args);

      const profile = await readProfile();
      if (!profile) return errText('Assess completed but no profile found at ' + PROFILE_PATH);

      let result = `nextmillionai — Assessment\n${'='.repeat(40)}\n\n` + profileSummary(profile);
      const coverageLines = out.split('\n').filter((l) => l.includes('Coverage:') || l.trim().startsWith('- ') || l.trim().startsWith('widen:'));
      if (coverageLines.length) result += '\n' + coverageLines.join('\n');
      result += `\n\nProfile: ${PROFILE_PATH}`;
      return text(result);
    } catch (e) { return errText(`assess failed: ${e.message}`); }
  }
);

// ── nma_get_profile ──────────────────────────────────────────────────────────

server.tool(
  'nma_get_profile',
  `Read the current AI coding profile (the local assessment JSON): dimensions, archetypes, positioning, work mode, wrapped stats, activity. Suggest nma_assess first if none exists.`,
  {
    raw: z.boolean().optional().describe('Return the full assessment JSON instead of a summary.'),
  },
  async ({ raw }) => {
    try {
      const profile = await readProfile();
      if (!profile) return text('No profile found. Run nma_assess first.');
      if (raw) return text(JSON.stringify(profile, null, 2));

      let out = `nextmillionai — Profile\n${'='.repeat(40)}\n\n` + profileSummary(profile);

      const workMode = profile.workMode?.dominant || {};
      if (workMode.id) {
        out += `\nWork mode: ${workMode.id}${workMode.line ? ` — "${workMode.line}"` : ''}\n`;
      }
      const ws = profile.wrappedStats || {};
      const hl = [];
      if (ws.maxParallelAgents) hl.push(`max parallel agents ${ws.maxParallelAgents}`);
      if (ws.longestStreakDays) hl.push(`longest streak ${ws.longestStreakDays}d`);
      if (ws.totalActiveHours) hl.push(`${ws.totalActiveHours}h total`);
      if (hl.length) out += `Highlights: ${hl.join(' · ')}\n`;
      out += `\nProfile: ${PROFILE_PATH}`;
      return text(out);
    } catch (e) { return errText(`get_profile failed: ${e.message}`); }
  }
);

// ── nma_get_report ───────────────────────────────────────────────────────────

server.tool(
  'nma_get_report',
  `Read the deep-report view of the assessment: the narrative blocks (narrative, what you built, decision patterns, strengths, growth areas, how you use AI), scores band, and experimental signals. Same single assessment JSON as the profile.`,
  {},
  async () => {
    try {
      const profile = await readProfile();
      if (!profile) return text('No profile found. Run nma_assess first.');

      const enr = profile.enrichment || {};
      let out = `nextmillionai — Report\n${'='.repeat(40)}\n\n`;
      if (enr.narrative) out += `Narrative: ${enr.narrative}\n`;
      if (enr.positioningLine) out += `Positioning: ${enr.positioningLine}\n`;
      if (enr.source === 'heuristic') {
        out += `(heuristic text — run nma_enrichment_request for an agent-written narrative)\n`;
      }
      out += '\n' + profileSummary(profile);

      if ((enr.strengths || []).length) {
        out += '\nStrengths:\n';
        for (const s of enr.strengths) out += `  - ${s.claim} (${s.evidence})\n`;
      }
      if ((enr.growthAreas || []).length) {
        out += '\nGrowth areas (private — only visible to you):\n';
        for (const g of enr.growthAreas) out += `  - ${g.observed} → ${g.nextSignal}\n`;
      }
      const exp = profile.experimental || {};
      if ((exp.signals || []).length) {
        out += '\nExperimental signals (never shared):\n';
        for (const s of exp.signals.slice(0, 8)) out += `  - ${s.label}: ${s.headline}\n`;
      }
      if ((exp.codeIntelligence || []).length) {
        out += `\nCode intelligence: ${exp.codeIntelligence.length} findings (run nma_get_profile raw=true for detail)\n`;
      }
      out += `\nBrowser view: nextmillionai report → http://localhost:${DEFAULT_PORT}/report`;
      return text(out);
    } catch (e) { return errText(`get_report failed: ${e.message}`); }
  }
);

// ── nma_enrichment_request / nma_enrichment_submit ──────────────────────────

server.tool(
  'nma_enrichment_request',
  `Get the enrichment prompt (ENRICHMENT-PROMPT.md filled with this user's real signals + bounded, secret-stripped excerpts). YOU — the user's own agent — should then produce the six-block JSON it asks for and pass it to nma_enrichment_submit. Derived-only: never include raw code, prompts, or ranking language. The narrative never changes scores and narrates positioning as ground truth.`,
  {},
  async () => {
    try {
      await runCLI(['enrich', '--yes']);
      const promptPath = join(DATA_DIR, 'enrichment_prompt.txt');
      const prompt = await readFile(promptPath, 'utf-8');
      return text(
        `Follow the instructions below and produce ONLY the JSON object, then call nma_enrichment_submit with it.\n\n${prompt}`
      );
    } catch (e) { return errText(`enrichment_request failed: ${e.message}`); }
  }
);

server.tool(
  'nma_enrichment_submit',
  `Submit the six-block enrichment JSON produced from nma_enrichment_request. It is validated on ingest (off-schema keys, raw/fenced code, and ranking language are rejected — fix and resubmit ONCE if rejected). Revocable: nextmillionai enrich --revoke.`,
  {
    result: z.record(z.any()).describe('The six-block enrichment JSON object (narrative, positioningLine, whatYouBuilt, decisionPatterns, strengths, growthAreas, howYouUseAI).'),
  },
  async ({ result }) => {
    let dir;
    try {
      dir = await mkdtemp(join(tmpdir(), 'nma-enrich-'));
      const file = join(dir, 'result.json');
      await writeFile(file, JSON.stringify(result, null, 2));
      const out = await runCLI(['enrich', '--submit', file]);
      return text(out.trim());
    } catch (e) {
      return errText(`enrichment_submit failed: ${e.message}`);
    } finally {
      if (dir) await rm(dir, { recursive: true, force: true }).catch(() => {});
    }
  }
);

// ── nma_export ───────────────────────────────────────────────────────────────

server.tool(
  'nma_export',
  `Produce the static, self-hostable artifact: profile + report views rendering from one redacted assessment.json. Visibility-filtered and verified — no raw prompts, experimental signals, hidden projects, or private growth. Nothing leaves the machine; the user can drop the folder on any static host.`,
  {
    out: z.string().optional().describe('Output directory (default: ./nextmillionai-export).'),
  },
  async ({ out }) => {
    try {
      const args = ['export'];
      if (out) args.push('--out', out);
      const result = await runCLI(args);
      return text(result.trim());
    } catch (e) { return errText(`export failed: ${e.message}`); }
  }
);

// ── nma_serve ────────────────────────────────────────────────────────────────

server.tool(
  'nma_profile_url',
  'Get the local URL for the browser profile/report. Checks whether the local server is running (it does not start one).',
  {
    port: z.number().optional().describe(`Server port (default: ${DEFAULT_PORT}).`),
  },
  async ({ port }) => {
    const p = port || DEFAULT_PORT;
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 2000);
      const res = await fetch(`http://localhost:${p}/api/profile/meta`, { signal: controller.signal });
      clearTimeout(timeout);
      if (res.ok) {
        return text(`Profile server running.\n  Profile: http://localhost:${p}/profile\n  Report:  http://localhost:${p}/report`);
      }
    } catch { /* not running */ }
    return text(`Server not running. Start it with:\n  nextmillionai report --port ${p}\nThen visit http://localhost:${p}/profile`);
  }
);

// ── nma_publish / nma_unpublish (gated) ──────────────────────────────────────

server.tool(
  'nma_publish',
  `OPT-IN NETWORK PUBLISH — the only tool that sends data anywhere.
Publishes the user's curated, visibility-filtered, derived-only profile to a registry so hiring managers' agents can discover them. Never sends raw code, transcripts, prompts, hidden projects, private growth, or experimental signals. Revocable via nma_unpublish.

CONSENT PROTOCOL (mandatory):
1. First call with confirm=false (default): returns exactly what would be sent. Show this to the user.
2. Only after the user explicitly says yes, call again with confirm=true.
Never call with confirm=true without the user's explicit confirmation in this conversation.`,
  {
    confirm: z.boolean().optional().describe('true ONLY after the user explicitly confirmed publishing.'),
    registry: z.string().optional().describe(`Registry URL (default ${DEFAULT_REGISTRY} — self-hosted; the hosted nextmillionai network is roadmap).`),
  },
  async ({ confirm, registry }) => {
    try {
      const args = ['publish'];
      if (registry) args.push('--registry', registry);
      if (!confirm) {
        args.push('--dry-run');
        const out = await runCLI(args);
        return text(out.trim() + '\n\nNothing was sent. Show the user the sections above and ask for explicit confirmation, then call nma_publish again with confirm=true.');
      }
      args.push('--confirm');
      const out = await runCLI(args);
      return text(out.trim());
    } catch (e) { return errText(`publish failed: ${e.message}`); }
  }
);

server.tool(
  'nma_unpublish',
  'Revoke a network publish: removes the profile from the registry and clears local publish state.',
  {},
  async () => {
    try {
      const out = await runCLI(['unpublish']);
      return text(out.trim());
    } catch (e) { return errText(`unpublish failed: ${e.message}`); }
  }
);

// ── nma_discover_builders (the hiring-manager agent side) ───────────────────

server.tool(
  'nma_discover_builders',
  `Query a nextmillionai registry for builders who opted in to be discovered. Returns only what each builder explicitly published. Filters: leverage mode (prompting | harnessing | designs_the_loop), build domain (products | ai_products | ai_systems), tech domain (e.g. python). Positioning is a map, not a ranking — results are matches, not a leaderboard.`,
  {
    registry: z.string().optional().describe(`Registry URL (default ${DEFAULT_REGISTRY}).`),
    leverage: z.string().optional().describe('Filter: prompting | harnessing | designs_the_loop.'),
    domain: z.string().optional().describe('Filter: products | ai_products | ai_systems.'),
    tech: z.string().optional().describe('Filter: tech domain name, e.g. python, TypeScript.'),
    builderId: z.string().optional().describe('Fetch one builder\'s full published profile by id.'),
  },
  async ({ registry, leverage, domain, tech, builderId }) => {
    const base = (registry || DEFAULT_REGISTRY).replace(/\/$/, '');
    try {
      if (builderId) {
        const res = await fetch(`${base}/v1/builders/${builderId}`);
        if (!res.ok) return errText(`Registry returned ${res.status}`);
        return text(JSON.stringify(await res.json(), null, 2));
      }
      const params = new URLSearchParams();
      if (leverage) params.set('leverage', leverage);
      if (domain) params.set('domain', domain);
      if (tech) params.set('tech', tech);
      const res = await fetch(`${base}/v1/builders?${params}`);
      if (!res.ok) return errText(`Registry returned ${res.status}`);
      const data = await res.json();
      if (!data.count) return text('No opted-in builders match those filters.');
      let out = `${data.count} opted-in builder(s):\n\n`;
      for (const b of data.builders) {
        out += `- ${b.name || '(unnamed)'}${b.primaryTitle ? ` — ${b.primaryTitle}` : ''}\n`;
        out += `  leverage: ${b.leverageMode || '?'} · builds: ${b.buildDomain || '?'} · tech: ${(b.techDomains || []).join(', ')}\n`;
        out += `  id: ${b.builderId}\n`;
      }
      return text(out);
    } catch (e) {
      return errText(`Could not reach registry at ${base}: ${e.message}`);
    }
  }
);

// ── nma_growth_edge ──────────────────────────────────────────────────────────

server.tool(
  'nma_growth_edge',
  `Private growth guidance from the profile's weakest measured dimensions and detected risk signals. Mode-aware and honest: suggestions are next signals to build, not rankings against anyone.`,
  {},
  async () => {
    try {
      const profile = await readProfile();
      if (!profile) return text('No profile found. Run nma_assess first.');

      const dims = profile.dimensions || {};
      const antiPatterns = profile.antiPatterns || [];
      const archetypes = profile.archetypes || [];

      let out = `nextmillionai — Growth Edge (private)\n${'='.repeat(45)}\n\n`;

      const backendGe = profile.growthEdge || {};
      if (backendGe.suggestion) {
        out += `Primary growth edge: ${backendGe.suggestion}\n`;
        if (backendGe.context) out += `Context: ${backendGe.context}\n`;
        out += '\n';
      }

      const enrGrowth = (profile.enrichment || {}).growthAreas || [];
      if (enrGrowth.length) {
        out += 'Observed gaps → next signals:\n';
        for (const g of enrGrowth) out += `  - ${g.observed} → ${g.nextSignal}\n`;
        out += '\n';
      }

      const dimEntries = Object.entries(dims)
        .map(([key, val]) => ({ key, score: dimScore(val) }))
        .sort((a, b) => a.score - b.score)
        .slice(0, 2);
      if (dimEntries.length) {
        out += 'Lowest-measured dimensions (largest headroom):\n';
        for (const { key, score } of dimEntries) out += `  - ${titleCase(key)}: ${score}/100\n`;
        out += '\n';
      }

      if (antiPatterns.length) {
        out += 'Risk signals detected:\n';
        for (const p of antiPatterns) {
          out += `  ${p.icon || '!'} ${p.name}${p.risk ? ` — ${p.risk}` : ''}\n`;
        }
        out += '\n';
      }

      if (archetypes.length) {
        out += `Strongest patterns to build on: ${archetypes.slice(0, 2).map((a) => a.name).join(', ')}\n`;
      }
      out += '\nThis section is private — it never appears in shared or exported profiles.';
      return text(out);
    } catch (e) { return errText(`growth_edge failed: ${e.message}`); }
  }
);

// ── nma_compare_to_role ──────────────────────────────────────────────────────

server.tool(
  'nma_compare_to_role',
  `Compare the profile against a job description: which measured dimensions and archetypes the role emphasizes, where the fit is strong, and where the honest gaps are. Fit is about this role — never a ranking against other builders.`,
  {
    job_description: z.string().describe('The job description or role requirements to compare against.'),
  },
  async ({ job_description }) => {
    try {
      const profile = await readProfile();
      if (!profile) return text('No profile found. Run nma_assess first.');

      const dims = profile.dimensions || {};
      const archetypes = profile.archetypes || [];
      const composite = profile.composite || 0;
      const jd = job_description.toLowerCase();

      const dimKeywords = {
        signal_clarity: ['prompt engineering', 'ai-native', 'ai-assisted', 'copilot', 'claude', 'cursor', 'llm', 'ai tools'],
        build_stability: ['quality', 'testing', 'test-driven', 'code review', 'reliability', 'production-ready', 'robust', 'maintainable'],
        decision_weight: ['architect', 'system design', 'architecture', 'platform', 'planning', 'design decisions'],
        recovery_velocity: ['debug', 'troubleshoot', 'diagnose', 'incident', 'on-call', 'fast-paced', 'velocity', 'rapid', 'speed'],
        context_command: ['context', 'cross-functional', 'multi-service', 'end-to-end', 'full-stack', 'breadth'],
        orchestration_range: ['multi-agent', 'automation', 'ci/cd', 'devops', 'mcp', 'orchestration', 'workflow', 'pipeline'],
      };
      const archetypeKeywords = {
        'Agent Harness Builder': ['agent', 'autonomous', 'multi-agent', 'mcp', 'agent mode'],
        'Integration / MCP Engineer': ['integration', 'api', 'connector', 'mcp', 'cross-service', 'orchestration'],
        'Multi-Agent Orchestrator': ['multi-agent', 'parallel', 'fleet', 'orchestration', 'autonomous'],
        'System Thinker': ['architect', 'system design', 'infrastructure', 'platform', 'scalable', 'distributed'],
        'Rapid Prototyper': ['ship', 'prototype', 'launch', 'deploy', 'iterate', 'mvp', 'hackathon', 'startup'],
        'Code Weaver': ['quality', 'clean code', 'testing', 'review', 'reliability', 'production-ready'],
        'Production Guardian': ['devops', 'ci/cd', 'pipeline', 'automation', 'sre', 'monitoring'],
        'Context Engineer': ['context', 'prompt engineering', 'retrieval', 'rag', 'memory'],
        'CLI-Native Builder': ['cli', 'terminal', 'command line', 'shell', 'scripting'],
      };

      let totalDimRelevance = 0;
      let totalDimAlignment = 0;
      const dimAnalysis = [];
      for (const [dimKey, keywords] of Object.entries(dimKeywords)) {
        const matches = keywords.filter((kw) => jd.includes(kw));
        if (matches.length > 0) {
          const score = dimScore(dims[dimKey]);
          const relevance = Math.min(matches.length, 3);
          totalDimRelevance += relevance;
          totalDimAlignment += (score / 100) * relevance;
          const fit = score >= 70 ? 'STRONG' : score >= 40 ? 'MODERATE' : 'GAP';
          dimAnalysis.push({ label: titleCase(dimKey), score, fit, keywords: matches });
        }
      }

      const archetypeMap = Object.fromEntries(archetypes.map((a) => [a.name, a]));
      const archetypeAnalysis = [];
      for (const [archName, keywords] of Object.entries(archetypeKeywords)) {
        const matches = keywords.filter((kw) => jd.includes(kw));
        if (matches.length > 0) {
          const arch = archetypeMap[archName];
          const score = arch ? arch.score : 0;
          const fit = score >= 70 ? 'STRONG' : score >= 40 ? 'MODERATE' : 'GAP';
          archetypeAnalysis.push({ name: archName, score, fit, keywords: matches, icon: arch?.icon || '?' });
        }
      }

      const dimFitRatio = totalDimRelevance > 0 ? totalDimAlignment / totalDimRelevance : 0.5;
      const strongArch = archetypeAnalysis.filter((a) => a.fit === 'STRONG').length;
      const archetypeFitRatio = strongArch / (archetypeAnalysis.length || 1);
      const overallFit = Math.round(dimFitRatio * 50 + archetypeFitRatio * 30 + (composite / 100) * 20);
      const fitLabel =
        overallFit >= 80 ? 'Strong fit' :
        overallFit >= 60 ? 'Good fit' :
        overallFit >= 40 ? 'Partial fit' : 'Notable gaps';

      let out = `nextmillionai — Role Comparison\n${'='.repeat(45)}\n\n`;
      out += `Role fit: ${overallFit}/100 (${fitLabel}) — fit for THIS role, not a ranking of you as a builder.\n\n`;

      if (dimAnalysis.length) {
        out += 'Dimension alignment:\n';
        for (const d of dimAnalysis) {
          const icon = d.fit === 'STRONG' ? '+' : d.fit === 'MODERATE' ? '~' : '-';
          out += `  [${icon}] ${d.label}: ${d.score}/100 (${d.fit}) — matched: ${d.keywords.join(', ')}\n`;
        }
        out += '\n';
      }
      if (archetypeAnalysis.length) {
        out += 'Archetype alignment:\n';
        for (const a of archetypeAnalysis) {
          const icon = a.fit === 'STRONG' ? '+' : a.fit === 'MODERATE' ? '~' : '-';
          out += `  [${icon}] ${a.icon} ${a.name}: ${a.score} (${a.fit}) — matched: ${a.keywords.join(', ')}\n`;
        }
        out += '\n';
      }
      const gaps = [...dimAnalysis, ...archetypeAnalysis].filter((g) => g.fit === 'GAP');
      if (gaps.length) {
        out += 'Honest gaps for this role:\n';
        for (const g of gaps) {
          out += `  - ${g.label || g.name} (${g.score}) — role emphasizes: ${g.keywords.join(', ')}\n`;
        }
        out += '\nUse nma_growth_edge for next signals to build.\n';
      }
      return text(out);
    } catch (e) { return errText(`compare_to_role failed: ${e.message}`); }
  }
);

// ─── Start ───────────────────────────────────────────────────────────────────

const transport = new StdioServerTransport();
await server.connect(transport);
