---
name: "Feature: Snapshot Diff Reporting"
about: Provide --diff-latest detailed change reports between runs
labels: enhancement, priority-high
---

# Snapshot Diff Reporting

## Summary

Generate human + machine readable reports of added/removed/modified files between consecutive runs.

## Goals


- Persist previous state (already done) and compute delta.
- Output JSON diff with counts & per-file details.
- Append high-level diff summary to project README.
- Optional `--diff-format text|json|both`.

## Acceptance Criteria


- Diff JSON includes added/removed/modified/unchanged_count.
- README gains a section with last diff summary when flag is used.
- Returns non-zero exit code if modified > threshold when `--diff-fail-modified N` provided (future).

## Non-Goals


- Binary patch generation.

## Implementation Sketch


- Extend existing `_compute_diff` result injection.
- Write README section insertion (idempotent anchor markers).
- Add CLI threshold flag later.

## Risks


- Large diff JSON files for huge sites (consider compression if > size limit).

## References

ROADMAP: Section 5 – Priority ⭐
