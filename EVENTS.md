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

## AI Integration Events

The interactive GUI (and optional auto-retry AI assist) emits additional events when AI suggests or applies configuration mutations. These are GUI-scope (not emitted by headless `clone_site` unless you wire similar hooks):

- `ai_changes_proposed` (changes)
  - Emitted when the AI assistant parses a JSON Changes line. Nothing has been applied yet.
  - `changes`: object mapping whitelisted field -> proposed value.

- `ai_changes_risk` (changes, risks)
  - Emitted immediately after risk heuristics run on a proposal (prior to user applying) if any risky fields detected.
  - `changes`: full proposed change dict (same as above)
  - `risks`: object mapping field -> human-readable risk description (e.g. `{ "jobs": "increase 8->24 (>2x)" }`)

- `ai_changes_applied` (changes)
  - Emitted after user accepts a subset (or all) of the proposed fields in the diff preview dialog.
  - `changes`: object of actually applied field -> value.

- `ai_changes_undo` (changes)
  - Emitted when the user invokes Undo Last AI Changes (reverts most recent applied set via inverse snapshot).
  - `changes`: object of fields restored to their prior values.

### AI Risk Heuristics (current)

Heuristics are intentionally conservative and may expand over time; they flag but never block:

| Field | Condition | Example risk string |
|-------|-----------|---------------------|
| jobs | proposed > current*2 and >=8 | `increase 6->16 (>2x)` |
| failure_threshold | (new - old) > 0.1 OR new > 0.35 | `raised 0.15->0.40` |
| relaxed_tls | newly enabled | `relaxes TLS verification` |
| checksums | disabled when previously enabled | `disables checksums` |
| verify_after | disabled when previously enabled | `disables verification` |

Consumers should treat `ai_changes_risk` as an advisory; users can still apply changes.

## Adaptive Concurrency Event

When experimental adaptive concurrency logic elects to restart wget2 with fewer threads, the core emits:

- `adaptive_concurrency_adjust` (stage, old_jobs, new_jobs, err_ratio)
  - `stage`: currently `restart` when a mid-run restart is initiated.
  - `old_jobs`: previous requested jobs value.
  - `new_jobs`: reduced jobs value selected.
  - `err_ratio`: observed error line ratio triggering the adjustment (approximate, 0-1).

This event is emitted only if `adaptive_concurrency` flag is enabled in the configuration.

## Backward Compatibility

- Added fields are purely additive. Existing consumers should ignore unknown keys.
- `summary_final` is additive; `summary` remains the canonical aggregation emitted from within `clone_site`.

## Example

```json
{"event":"start","ts":"2025-10-01T12:00:00Z","seq":1,"run_id":"...","schema_version":1,"tool_version":"1.1.0","url":"https://example.com","output":"/out/site"}
```
