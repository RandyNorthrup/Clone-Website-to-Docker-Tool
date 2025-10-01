---
name: "Feature: Incremental Clone"
about: Skip unchanged assets and optional prune based on previous state
labels: enhancement, priority-high
---

# Incremental Clone

## Summary

Enable delta-based cloning that avoids re-downloading resources whose size + mtime (and optionally hash) match previous snapshot.

## Goals


- `--incremental` already seeds timestamping; extend to compare saved state.
- Skip identical files (do not re-hash unless size/mtime changed).
- Optional `--prune-removed` to delete files missing upstream.
- Update state atomically after successful run.

## Acceptance Criteria


- Second run of same site reports fewer network fetches (log summary).
- State file updated only after successful completion.
- Prune deletes only files not present in remote (guard against network errors).

## Non-Goals


- Fine-grained partial HTTP range diffs.

## Implementation Sketch


- Extend `_snapshot_file_hashes` to allow lightweight mode (size+mtime only).
- Compare previous `files` map; build skip set.
- (Future) Provide stats: skipped_count, revalidated_count.

## Risks


- Clock skew on remote server (mtime mismatches) – default to re-download if ambiguous.

## References

ROADMAP: Section 1 – Priority ⭐
