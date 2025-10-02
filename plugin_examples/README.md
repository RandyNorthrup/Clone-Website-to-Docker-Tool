# Plugin Examples

This folder contains minimal, documented examples of the current plugin API surface.

Plugin discovery: any `*.py` file in the directory passed via `--plugins-dir` (CLI) or chosen in the GUI will be imported. Each module may optionally expose zero or more of the following callables:

## Lifecycle Hooks

### `pre_download(context)`
Called before running `wget2`.

`context` keys:
- `url`: target URL
- `dest`: destination base folder
- `output_folder`: fully qualified output project folder (dest + docker_name)

Use cases: sanity checks, environment preparation, writing seed files, logging.

### `post_asset(rel_path, data, context)` (legacy signature) OR `post_asset(rel_path: str, data: bytes, ctx: dict) -> Optional[Union[str, bytes]]`
Called for each downloaded asset (currently limited to file extensions: `.html`, `.htm`, `.css`, `.js`, `.json`, `.txt` plus some images). If the function returns a value, the asset content is replaced.

Return types:
- `str`: will be UTF-8 encoded
- `bytes` / `bytearray`: used directly
- `None`: no change

`context` keys:
- `output_folder`
- `site_root`
- `manifest`: current manifest dict (may be partially populated)

### `finalize(output_folder, manifest_dict, context)` (expanded legacy) OR `finalize(context)` (minimal dict form)
Called after all phases (clone, prerender, diff, checksums, verification) just before optional cleanup. Allows mutation of the manifest before it is re-written to disk.

The implementation should catch its own exceptions where possible; uncaught exceptions are logged but do not abort the clone.

## Metrics Exposure

During the `post_asset` phase the system tracks how many assets each plugin modified; results are stored in the manifest under `plugin_modifications` and surfaced in the final `summary` JSON log event.

## Safety Guidelines

- Avoid slow network calls inside `post_asset` (runs once per asset and is sequential per file).
- Fail soft: wrap risky code portions in `try/except`.
- Keep modifications idempotent (running the plugin twice shouldn’t corrupt content).

## Examples

- `rewrite_title.py` – appends a marker to `<title>` in HTML pages.
- `inject_banner.py` – inserts a disclosure banner after opening `<body>`.
- `manifest_note.py` – adds a custom note into the manifest during `finalize`.

---

Contributions welcome: add focused examples (one concern per file) with concise docstrings.
