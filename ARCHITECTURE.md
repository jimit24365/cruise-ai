# Architecture

## Module map

| Module | Paths | Purpose |
|--------|-------|---------|
| **core** | `nextmillionai/scoring.py`, `nextmillionai/schema.py`, `nextmillionai/signal_registry.py`, `nextmillionai/docs/**` | Scoring engine, the one data contract, derived-field registry, methodology docs |
| **scan** | `nextmillionai/scanner.py`, `nextmillionai/adapters/**`, `nextmillionai/code_intel.py`, `nextmillionai/history.py` | Multi-tool session scanner, per-tool adapters, opt-in code scan, durable ledger |
| **serve** | `nextmillionai/hub.py`, `nextmillionai/build_profile.py`, `nextmillionai/live.py` | HTTP server, CLI entry point, live file-watcher/SSE |
| **net** | `nextmillionai/network.py`, `nextmillionai/network_server.py`, `nextmillionai/sync_merge.py` | The ONLY outbound module (publish/sync, opt-in) + reference registry + device merge |
| **face** | `nextmillionai/static/**` | Frontend HTML/CSS/JS (one assessment JSON renders both views) |
| **bridge** | `nextmillionai-mcp/**` | MCP server for Claude/Cursor |

### Shared utilities

`paths.py`, `profile_data.py`, `cliui.py`, `consent.py`, `export.py`,
`visibility.py`, `business_fit.py`, `enrichment.py`, `__init__.py`, and
`__main__.py` belong to no single module — they are owned by maintainers.

## Dependency diagram

```
scan → core → serve → face
                ↓
               net   (outbound only, opt-in: publish / sync)
                ↕
              bridge
```

## Data-contract rule

`profile.json` and `scan_results.json` schemas are owned by **core**. Other
modules consume the contract but must not change it.

Any schema change requires:

1. A core-owner review.
2. A CHANGELOG entry.
