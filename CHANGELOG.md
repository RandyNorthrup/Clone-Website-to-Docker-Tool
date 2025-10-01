# Changelog

All notable changes to this project will be documented here. The format loosely follows Keep a Changelog.

## [1.1.1] - 2025-10-01

### GUI Resizing

- Window can now expand horizontally only via the right edge; configuration pane width is fixed to preserve layout stability.
- Removed enforced maximum width while keeping computed minimum width.
- Added left-edge anchor (handled in `resizeEvent` / `moveEvent`) so expansion never drags the config area.

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
