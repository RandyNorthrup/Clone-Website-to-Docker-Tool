---
name: "Feature: Config File Support"
about: Add --config (JSON/YAML) load + GUI export/import
labels: enhancement, priority-high
---

## Summary

Implement configuration file support so users can declare repeatable cloning profiles.

## Goals

- Support `--config path.{json|yml|yaml}` merging into CLI args (CLI overrides file).
- GUI: Export current selections to a config file; Import to restore.
- Document precedence & supported keys.

## Acceptance Criteria

- Passing a config file populates defaults when equivalent CLI flags not provided.
- Invalid / unreadable config produces a clear warning, does not abort.
- GUI export/import round trip restores all applicable fields (URL excluded by design? confirm).

## Non-Goals

- Remote config fetch (future idea)
- Validation beyond type/shape sanity.

## Implementation Sketch

- Reuse `_load_config_file` (already added headless path).
- Create `config_io.py` (GUI-safe) with `load_config(dict)`, `serialize_current()`.
- Add two menu buttons (File > Import Config…, File > Export Config…).

## Risks

- Overwriting user selections inadvertently (resolve via explicit confirmation if dirty state changed).

## References

ROADMAP: Section 4 (Architecture & Extensibility) – Priority ⭐
