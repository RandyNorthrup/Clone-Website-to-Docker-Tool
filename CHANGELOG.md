# Changelog

All notable changes to this project will be documented here. The format loosely follows Keep a Changelog.

## [1.1.7] - 2025-10-01

### Added (QA & UX)

- Test coverage for new fidelity flags: reproduction command now asserted to include `--dom-stable-ms`, `--dom-stable-timeout-ms`, and `--capture-graphql` when configured.
- Manifest field tests ensuring presence of `dom_stable_ms`, `dom_stable_timeout_ms`, `capture_graphql`, and promoted `graphql_captured_count`.
- GUI tooltips added for DOM stabilization spin boxes and GraphQL capture checkbox for clearer guidance.

### Internal

- Version bump to 1.1.7 (no core functional logic changes besides metadata & GUI tooltip additions / tests).

## [1.1.6] - 2025-10-01

### Added (GraphQL Capture)

- `--capture-graphql` flag + GUI integration forthcoming (CLI first) to persist GraphQL POST operations during prerender under `_graphql/` as JSON bundles containing operation name, query text, variables, HTTP status, and parsed response payload.
- Manifest additions: `capture_graphql` boolean and `graphql_captured_count` (promoted from prerender stats).
- Reproduction command includes `--capture-graphql` when active.

### Notes (GraphQL)

- Detection heuristic: POST + `application/json` content-type whose request body contains `"query"` or newline-prefixed `query` / `mutation` tokens.
- Batched GraphQL arrays are not yet decomposed—each request saved as-is (future enhancement: split batches per operation).
- Combine with `--dom-stable-ms` for more deterministic snapshots of data-driven UIs.

## [1.1.5] - 2025-10-01

### Added (DOM Stabilization Heuristic)

- New `--dom-stable-ms N` flag (GUI: Dom Stable (ms)) to require a quiet window of N milliseconds with no DOM mutations before capturing each prerendered page. Uses a lightweight `MutationObserver` to update a timestamp; polling stops when the window elapses or timeout triggers.
- New `--dom-stable-timeout-ms M` to cap the additional wait per page (default 4000ms). Prevents pathological long waits on pages with constant animations.
- Manifest fields: `dom_stable_ms`, `dom_stable_timeout_ms`; prerender stats enriched with `dom_stable_pages` (pages achieving stability) and `dom_stable_total_wait_ms` (aggregate wait).
- Reproduction command includes these flags when active.

### Notes (DOM Stabilization)

- Recommended starting value: 500–1000ms. Larger values increase fidelity but slow prerender dramatically on very dynamic pages.
- If the timeout is hit without a quiet window, the current DOM is captured (best-effort mode).
- Complements `--prerender-scroll`; combine scroll passes followed by stabilization to allow lazy content to load then settle.


## [1.1.3] - 2025-10-01

## [1.1.4] - 2025-10-01

### Added (Prerender Scroll)

- New `--prerender-scroll N` flag and GUI field (Scroll Passes) to perform N incremental scroll passes per prerendered page (each pass scrolls to `document.body.scrollHeight` then waits ~350ms) to trigger lazy/infinite content loading.
- Manifest field `prerender_scroll_passes` records configured scroll passes; prerender stats now include `scroll_passes`.
- Reproduction command includes `--prerender-scroll` when non-zero.

### Notes

- Use small values (1-3) first; high values can significantly increase prerender time on long feeds.
- Combine with hook script for more complex pagination or button-triggered load behaviors.


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
