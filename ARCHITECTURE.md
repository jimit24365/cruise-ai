# Architecture

## Module map

| Module | Paths | Purpose |
|--------|-------|---------|
| **core** | `cruise_ai/scoring.py`, `cruise_ai/schema.py`, `cruise_ai/signal_registry.py`, `cruise_ai/docs/**` | Scoring engine, the one data contract, derived-field registry, methodology docs |
| **scan** | `cruise_ai/scanner.py`, `cruise_ai/adapters/**`, `cruise_ai/code_intel.py`, `cruise_ai/history.py` | Multi-tool session scanner, per-tool adapters, opt-in code scan, durable ledger |
| **serve** | `cruise_ai/hub.py`, `cruise_ai/build_profile.py`, `cruise_ai/live.py` | HTTP server, CLI entry point, live file-watcher/SSE |
| **net** | `cruise_ai/network.py`, `cruise_ai/network_server.py`, `cruise_ai/sync_merge.py` | The ONLY outbound module (publish/sync, opt-in) + reference registry + device merge |
| **face** | `cruise_ai/static/**` | Frontend HTML/CSS/JS (one assessment JSON renders both views) |
| **bridge** | `cruise_ai-mcp/**` | MCP server for Claude/Cursor |

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
