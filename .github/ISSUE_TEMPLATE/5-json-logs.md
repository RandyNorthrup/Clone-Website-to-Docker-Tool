---
name: "Feature: Structured JSON Logs"
about: Add --json-logs comprehensive machine-readable event output
labels: enhancement, priority-high
---

# Structured JSON Logs

## Summary

Provide consistent JSON event stream for integration with pipelines, dashboards, and regression analyzers.

## Goals


- Extend current minimal JSON events (plugins, asset mods) to all phases.
- Standard schema fields: timestamp, level, event, phase, url/path, meta.
- Support `--json-logs-pretty` for human debugging.
- Ensure log lines are single-line JSON for easy parsing (unless pretty flag set).

## Acceptance Criteria


- Clone emits events: start, phase_progress, rate_update, api_capture, router_update, finish.
- Prerender emits per-page event with status (success/fail) & duration.
- Docker build emits build_start, build_log_chunk (optional), build_finish.
- Checksums & verification emit checksum_progress & verify_result.

## Non-Goals


- Persistent log indexing or search UI.

## Implementation Sketch


- Introduce `log_json(event, **fields)` helper gating on flag.
- Replace ad-hoc prints where feasible while retaining human output (dual-mode).

## Risks


- Performance overhead if too chatty; mitigate via throttling existing rate & count updates.

## References

ROADMAP: Section 3 – Priority ⭐
