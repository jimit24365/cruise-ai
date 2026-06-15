# Multi-device sync — one profile across machines

`nextmillionai sync` merges the evidence from every machine you build on
into ONE profile, using a **private git repo YOU own** as the store —
your account, your repo, revocable any time. nextmillionai never sees it.

```bash
# once, on each device (a PRIVATE repo you created):
nextmillionai sync --repo git@github.com:YOU/nma-sync.git

# afterwards, whenever you want to merge:
nextmillionai sync            # push this device, pull the others
nextmillionai assess --rescan # fold the union into your profile
nextmillionai sync --status   # local state, no network
nextmillionai sync --revoke   # remove THIS device from the store
```

## What syncs (derived-only — the same class as publish)

One JSON per device under `devices/` in your repo:

| Synced | Why |
|---|---|
| Session ledger keys (`tool:session_id`) per day | dedupe keys |
| Per-repo commit counts per day + repo names | commit dedupe unit |
| Activity day records (counts, tools, AI-mix ratio) | calendar union |

**Never synced:** prompts, transcripts, code, file paths, scores,
raw session content. Raw-data sync does not exist — there is no flag
for it.

## The merge rule (deterministic)

Recomputed from the deduped union — never by adding per-device totals:

- **Sessions** — union of ledger keys; a session counts once no matter
  how many times it syncs.
- **Commits** — per (repo, day): the **max** across devices. The same
  repo cloned on two machines holds the same commits, so max = dedupe;
  distinct repos sum cleanly. Overlapping repos never double-count.
- **Repos** — union by name; per-repo totals take the max.
- **Activity calendar** — the union of all devices' days; the heatmap
  spans every machine. Locally-unknown days are tagged `synced: true`.
- **Scores — never merged.** Dimension scores need raw local signals
  (prompt stats, plan-mode, dispatches) that deliberately do not sync.
  Each device's scores describe that device; the merged view adds
  cross-device *evidence* (activity, session counts, device list),
  not score inputs.

Conflict handling: each device only ever writes its own
`devices/<deviceId>.json` — last write wins per device; the merged view
is recomputed from the union on every assess.

## Failure honesty

- **Auth failure / offline** — sync defers with a clear message; local
  assessment is never blocked or degraded.
- **Single device** — sync is a no-op for merging (nothing to merge);
  the profile carries no `multiDevice` section.
- **Revoke** — removes this device's snapshot from the repo, clears the
  local mirror and config. Other devices keep theirs.

## Privacy placement

The outbound transport (`git push`/`pull` to your repo) lives in
`network.py` — the one sanctioned outbound module — behind the explicit
`cmd_sync` command, exactly like publish. The merge itself
(`sync_merge.py`) is pure local arithmetic and is the only part the
assessment path touches: it reads the local snapshot mirror under
`~/.nextmillionai/data/sync/devices/`, no network anywhere.
