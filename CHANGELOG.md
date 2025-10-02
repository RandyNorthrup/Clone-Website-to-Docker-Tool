# Changelog

All notable changes to this project will be documented here. The format loosely follows Keep a Changelog.

## [1.1.3] - 2025-10-01

### Added (Storage Capture)

- Added `--capture-storage` option to snapshot `localStorage` and `sessionStorage` for each prerendered page (writes JSON files under `_storage/` mirroring HTML path with `.storage.json` suffix).
- Manifest fields: `capture_storage` (bool) and `storage_captured_count` (count in `prerender_stats` promoted fields).

### Changed (Prerender Output)

- Prerender return stats now include `storage_captured` count; reproduction command includes `--capture-storage` when active.

### Notes (Scope)

- Only key/value pairs accessible to page scripts are captured; IndexedDB/service workers still pending roadmap.


## [1.1.2] - 2025-10-01

### Added (Extended API Capture)

- Extended prerender API capture beyond JSON: new `--capture-api-types` (comma or slash separated content-type prefixes) and `--capture-api-binary` (optional common binary types: pdf, images, octet-stream, audio/video). Writes responses under `_api/` with inferred extensions.
- Manifest fields `capture_api_types` and `capture_api_binary` record configuration.

### Changed (Reproduction Command)

- Reproduction command now includes new capture flags when set.
- README updated previously (no additional doc changes needed for this incremental feature; future docs section pending).

### Notes (Behavior)

- Default behavior (without new flags) remains JSON-only capture to avoid disk overhead.

## [1.1.1] - 2025-10-01

### GUI Resizing

- Window can now expand horizontally only via the right edge; configuration pane width is fixed to preserve layout stability.
- Removed enforced maximum width while keeping computed minimum width.
- Added left-edge anchor (handled in `resizeEvent` / `moveEvent`) so expansion never drags the config area.

### Documentation

- Added "Maximum Fidelity Mode" section with power profile recipe & hook scaffold.
- Corrected outdated note claiming router event interception was not implemented.

## [1.1.0] - 2025-10-01

### Added (Modularization)

- Packaging refactor: PySide6 moved to optional `gui` extra (`pip install cw2dt[gui]`).
- `__all__` export list in `cw2dt_core` defining stable public API.
- Friendly dispatcher message when GUI dependencies are missing.
- `CHANGELOG.md` introduced.

### Changed

- Version bump to 1.1.0.
- `__version__` updated and README architecture note references modular design.

## [1.0.1] - 2025-10-01

### Added (Initial)

- Modular split finalized (`cw2dt_core.py`, `cw2dt_gui.py`, minimal `cw2dt.py`).
- Packaging metadata (`pyproject.toml`, `MANIFEST.in`).

## [1.0.0] - 2025-09-??

### Added

- Initial monolithic implementation (preserved as `cw2dt_working.py`).
