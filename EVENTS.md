# Event Schema & Catalog

This document describes the structured JSON events emitted when `--json-logs` or `--events-file` is used.

## Envelope
Each event line is a single JSON object (NDJSON). Common fields:

| Field | Type | Description |
|-------|------|-------------|
| event | string | Event name identifier |
| ts | string (ISO8601 UTC) | Timestamp of emission |
| seq | integer | Monotonic counter starting at 1 per run |
| run_id | string | Stable UUID4 hex for the run |
| schema_version | integer | Event schema version (matches `SCHEMA_VERSION`) |
| tool_version | string | Tool version from `VERSION.txt` or `unknown` |

Additional fields vary per event.

## Core Lifecycle Events
- `start` (url, output)
- `phase_start` (phase, ...phase-specific)
- `phase_end` (phase, success?, stats...)
- `canceled` (phase)
- `timings` (total_measured_seconds, clone_seconds, prerender_seconds?, build_seconds?)
- `summary` (success, docker_built, canceled, timings, diff?, plugin_modifications?, js_strip_stats?)
- `summary_final` (success, docker_built, exit_code, run_id)

## Plugin Events
- `plugin_loaded` (name)
- `plugin_load_failed` (name, error)
- `post_asset_progress` (processed, total, modified)
- `post_asset_end` (processed, modified, total, plugin_modifications)
- `post_asset_error` (error)
- `plugin_finalize_start` (name)
- `plugin_finalize_end` (name)
- `plugin_finalize_error` (name, error)

## Prerender / Router Events
- `phase_start` (phase=prerender, max_pages)
- `phase_end` (phase=prerender, pages_processed, routes_discovered, api_captured)
- `router_discovery` (optional future extension)

## Checksums / Verification
- `phase_start` (phase=verify)
- `phase_end` (phase=verify, status)
- `phase_error` (phase=verify, error)

## Docker
- `phase_start` (phase=build, image)
- `phase_end` (phase=build, success)

## Cleanup
- `phase_start` (phase=cleanup)
- `cleanup_removed` (files)
- `phase_end` (phase=cleanup, removed)

## Reporting
- `report_generated` (path, format)
- `report_error` (error)

## Error / Warning Patterns
- `phase_error` (phase, error)
- `plugin_finalize_error` (name, error)

## Stable Ordering
Ordering is currently: `start` → phase events → timings → summary → (headless exit path) summary_final.

`summary_final` is emitted only by the CLI (`headless_main`), not when calling `clone_site` directly. It includes an `exit_code`.

## Future Extensions
- Rich progress events (spinner frames) when `--progress=rich` is active.
- Regex safety warnings (`regex_warning`) for potentially catastrophic patterns.
- Structured diff chunk events if incremental streaming is requested.

## Backward Compatibility
- Added fields are purely additive. Existing consumers should ignore unknown keys.
- `summary_final` is additive; `summary` remains the canonical aggregation emitted from within `clone_site`.

## Example
```json
{"event":"start","ts":"2025-10-01T12:00:00Z","seq":1,"run_id":"...","schema_version":1,"tool_version":"1.1.0","url":"https://example.com","output":"/out/site"}
```
