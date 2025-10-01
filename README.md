# Clone Website to Docker Tool

A desktop + CLI utility to clone public or private websites using **wget2** (parallel, resumable, authenticated), optionally **prerender dynamic / JavaScript-driven pages** with Playwright, then package and serve everything with Docker + Nginx. Includes a modern dark UI, advanced controls, and full headless automation.

> Architecture Note (v1.0.1+): The project has been modularized into three primary modules:
>
> - `cw2dt_core.py` – all cloning, prerender, diff, checksum, docker & verification logic (public API surface)
> - `cw2dt_gui.py` – PySide6 GUI thin layer calling `clone_site()` with callback bridging
> - `cw2dt.py` – minimal dispatcher (decides headless vs GUI) keeping Qt out of headless imports
>
> The legacy monolith is preserved as `cw2dt_working.py` for historical reference only (no new features). Future enhancements will target the modular architecture.

---

## Features

- **Point-and-click cloning** (GUI) + full-featured **headless CLI**
- **wget2** engine: fast, parallel, resumable, convert-links, page requisites
- **Authenticated cloning**:
  - HTTP Basic (user / password)
  - Browser cookie import (`browser_cookie3`) for logged-in sessions
- **Dynamic / SPA support (optional)**:
  - Post-clone **Playwright prerender** of JavaScript-driven pages (`--prerender`)
  - Configurable crawl budget (`--prerender-max-pages`)
  - **API / XHR JSON capture** into `_api/` (`--capture-api`)
  - **Hook script** for page mutation (`--hook-script on_page(page, url, context)`)
  - Optional **absolute origin → relative URL rewrite** (disable via `--no-url-rewrite`)
- **Site hardening & control**:
  - Optional JavaScript stripping + CSP enforcement (`--disable-js`)
  - Download quota (size cap)
  - Bandwidth throttling
  - Parallel jobs (`-j`) control
  - Pre-clone item estimation (spider mode)
- **Self-contained output**: `Dockerfile`, `nginx.conf`, per-project README, imported cookies
- **Docker workflows**:
  - Build an image (`--build`) + optionally run (`--run-built`)
  - Serve directly from folder (bind-mount, no build) (`--serve-folder`)
  - Custom bind IP / host port / container port
  - One-click run/stop, open in browser, copy URL in GUI
- **Robust UX**:
  - Resume partial clones (continues where wget2 left off)
  - Dependency hints & install commands
  - Recent URL memory (last 10)
  - Weighted multi-phase progress (clone / prerender / build / cleanup)
  - Live bandwidth display (current transfer rate)
  - Live API capture counter during prerender (throttled updates)
    - Live router route discovery counter (when interception enabled)
- **Cross-platform**: macOS, Linux, Windows
- **Fail-soft optional features**: prerender gracefully skipped if Playwright not installed

---

## Requirements

Mandatory:

- **Python** 3.9+
- **PySide6** (`pip install PySide6`) for GUI mode
- **wget2** (not legacy wget) available on PATH
- **Docker** (only needed if you build or serve through containers)

Optional / On-Demand:

- **browser_cookie3** (`pip install browser_cookie3`) for cookie-based session reuse
- **Playwright** (for prerender / SPA support)
  - Install: `pip install playwright`
  - Then: `playwright install chromium`
  - Omit if you only need static wget2 mirroring

Notes:

- Host **nginx is NOT required**; the container uses `nginx:alpine`.
- If Playwright is absent, prerender features are skipped without failing the clone.

---

## Usage

### GUI

1. Enter the target URL and choose / create a destination folder.
2. (Optional) Set Docker image / project name, enable build.
3. (Optional) Open Advanced: quota, throttle, jobs, JS disable, prerender, API capture, hook script.
4. Click Clone / Prepare.
5. After completion: Run built image or Serve From Folder, open in browser, copy URL, or stop the container.

GUI Layout Notes:

- The center split position (between configuration and console) is fixed to prevent accidental layout shifts.
- You can still expand available console/log space by resizing the window horizontally: the left edge remains anchored and only the right edge grows (the configuration panel width is constant; the console expands).
- Vertical overflow in the configuration area is scrollable; horizontal scrolling is suppressed for readability.

### CLI

All features are surfaced via flags in `--headless` mode.

Basic static clone:

```bash
python cw2dt.py --headless \
  --url "https://example.com" \
  --dest "/path/to/output" \
  --docker-name site \
  --build --run-built --open-browser
```

Authenticated (cookies + quota + throttle):

```bash
python cw2dt.py --headless \
  --url "https://private.example.com" \
  --dest ~/Sites --docker-name portal \
  --size-cap 2G --throttle 4M --jobs 12 \
  --serve-folder --open-browser
```

Dynamic site with prerender + API capture:

```bash
python cw2dt.py --headless \
  --url "https://spa.example.com" \
  --dest ./out --docker-name spa-site \
  --prerender --prerender-max-pages 60 --capture-api \
  --hook-script ./hooks/spa_tweaks.py \
  --build --run-built --open-browser
```

Selective prerender without URL rewriting:

```bash
python cw2dt.py --headless \
  --url https://app.example.com \
  --dest ./mirror --docker-name app \
  --prerender --no-url-rewrite --prerender-max-pages 25
```

Disable JavaScript entirely after download (for offline hardening / audit):

```bash
python cw2dt.py --headless --url https://example.com --dest ./mirror --docker-name hardened --disable-js
```

---

## CLI Flag Reference

Core:

- `--url URL` Target site (required)
- `--dest PATH` Destination base folder (required)
- `--docker-name NAME` Project / image name
- `--build` Build Docker image after clone
- `--run-built` Run image after building
- `--serve-folder` Serve directly from folder (bind mount)
- `--open-browser` Open served URL in default browser
- `--jobs N` Parallel wget2 jobs (default auto: >=4)
- `--size-cap QUOTA` Download quota (e.g. 500M, 2G)
- `--throttle RATE` Limit rate (e.g. 500K, 4M)
- `--disable-js` Strip scripts + inject restrictive CSP post-clone
- `--headless` Enable CLI mode (must be first/among args)

Authentication:

- `--auth-user USER` + `--auth-pass PASS` HTTP Basic
  (Alternatively import session cookies via GUI cookies feature)
- `--cookies-file PATH` Load existing Netscape-format cookie file for wget2
- `--import-browser-cookies` Attempt automatic browser cookie extraction (installs browser_cookie3 if missing)

Prerender & Dynamic:

- `--prerender` Enable Playwright dynamic DOM capture
- `--prerender-max-pages N` Cap prerender traversal (default 40)
- `--capture-api` Persist application/json responses into `_api/`
- `--hook-script PATH` Python file exporting `on_page(page, url, context)`
- `--no-url-rewrite` Keep absolute origin URLs (skip origin→relative rewrite)

Router Interception (SPA):

- `--router-intercept` Activate client-side route discovery
- `--router-include-hash` Treat `#hash` as distinct routes
- `--router-max-routes N` Cap additional routes (default 200)
- `--router-settle-ms MS` Delay after load before snapshot (default 350)
- `--router-wait-selector CSS` Wait for selector per route
- `--router-allow PAT1,PAT2` Only keep matching regex routes
- `--router-deny PAT1,PAT2` Discard matching regex routes
- `--router-quiet` Suppress per-route "Router discovered:" log lines (still counts)

Other:

- `--estimate` Pre-clone spider to approximate item count
- `--build` Build docker image
- `--run-built` Run built image
- `--serve-folder` Serve via bind mount (no build)
- `--no-manifest` Skip writing clone_manifest.json and project README summary augmentation
- `--checksums` Generate SHA256 checksums for cloned HTML/HTM and captured API JSON files (writes into manifest). Note: adds I/O time proportional to file count.
- `--checksum-ext EXT1,EXT2` Additional file extensions to include in checksums (e.g. css,js,png); improves integrity coverage at extra cost.
- `--verify-after` Run checksum verification immediately after clone (fast mode by default; skips missing files instead of failing).
- `--verify-deep` Use with `--verify-after` for a deep verification (do not skip missing; missing or mismatched files will fail).
- `--verify-fast` Alias for `--verify-after` (fast mode).
- `--verify-checksums` (Deprecated) Legacy alias retained for backward compatibility (acts like `--verify-after`).
- `--selftest-verification` Internal developer self-test for checksum summary parsing (does not perform a clone).

Noise Reduction Tip:

If prerender + router interception yields many route discoveries, combine:

```bash
--prerender --router-intercept --router-quiet --router-allow "/products/,/docs/"
```

This limits traversal to matching routes while hiding the individual enqueue logs, yet the aggregate `Routes:` counter still updates.

---

## Output Layout

```text
<Destination>/<project_name>/
  Dockerfile
  nginx.conf
  <website content>
  README_<project>.md
  imported_cookies.txt
  clone_manifest.json (unless --no-manifest)
  .folder.default.<port>.conf

If `--checksums` is enabled, SHA256 hashes are embedded in `clone_manifest.json` under a `checksums` object mapping relative paths to their digest. This is useful for integrity verification, diffing between runs, or external audit pipelines. The checksum phase runs after cloning (and prerender if enabled) and reports progress in the GUI console (or periodic updates headless). To re-verify later you can script a simple walker comparing stored digests to freshly computed ones.
If extra extensions were provided via `--checksum-ext`, they appear in the manifest under `checksum_extra_extensions`.
If verification is requested (`--verify-after` / GUI "Verify after clone"), the tool invokes an internal verifier that recomputes and compares digests, appending a summary (status + counts) to both the manifest and project README. Fast mode (default) ignores missing files; deep mode flags them.
```

## Dynamic Rendering (Prerender) Details

When `--prerender` (or the GUI checkbox) is enabled:

1. The site is first mirrored with `wget2` (structure + assets).
2. Playwright launches headless Chromium and begins exploring from the start URL.
3. Each visited page's fully rendered DOM (`page.content()`) overwrites / creates the corresponding HTML file.
4. Links (`<a href>`) inside the same origin are queued until the `--prerender-max-pages` limit is hit.
5. If `--capture-api` is set, JSON/XHR responses with `Content-Type: application/json` are stored under `_api/` mirroring the path (adding `.json`).
6. If a `--hook-script` is provided and exports `on_page(page, url, context)`, it is invoked before HTML extraction (ideal for login flows, expanding lazy content, or scraping single-page app states).
7. Unless `--no-url-rewrite` is specified, absolute occurrences of the origin (`https://host`) are rewritten to relative paths for better relocatability inside containers or alternate domains.

### Live Metrics

During cloning / prerender you’ll see in the GUI status bar:

```text
Total progress: 42% • Cloning • Rate: 3.2M/s • API: 15 • Routes: 11
```

- Rate: Parsed from wget2 stderr in near real-time.
- API: Count of JSON responses captured so far (only when prerender + API capture enabled). The UI intentionally throttles updates to avoid flicker: it refreshes roughly every 0.4s, on every 5th capture, or on large jumps.
- Routes: Number of additional SPA routes discovered (throttled; updates every 3rd route, >0.5s, or big jump).

In headless mode, API capture increments are printed as they occur.

### Router Interception (SPA Route Discovery)

Enable with `--router-intercept` (and the corresponding GUI checkbox). This augments prerendering by detecting client-side navigations that don’t trigger full page loads (e.g., `history.pushState`, React/Vue/Angular/Next.js route changes, hash transitions, back/forward events).

Flags:


- `--router-intercept` — turn on interception
- `--router-include-hash` — treat distinct `#hash` fragments as separate routes
- `--router-max-routes N` — cap number of additional routes (default 200)
- `--router-settle-ms MS` — wait after initial load for auto route pushes (default 350ms)
- `--router-wait-selector CSS` — optional selector to await before snapshot (e.g. `#app-root`)
- `--router-allow PAT1,PAT2` — only routes matching any regex pattern are kept
- `--router-deny PAT1,PAT2` — discard routes matching any regex pattern (applied after allow)

GUI exposes: Router intercept, Include #hash, Max routes, Settle (ms), and Wait selector.

Additional GUI items: Allow / Deny regex fields (optional filtering) and live Routes counter in the status bar.

Behavior:

- Injects a small script patching `history.pushState/replaceState` and listening to `popstate`, `hashchange`, and link clicks.
- Newly discovered same-origin routes are enqueued (respecting `--prerender-max-pages` and route cap) and rendered like normal pages.
- Prevents duplicates via internal sets; large floods are bounded.
- Optional allow/deny regex filters constrain route explosion for param-heavy SPAs.
- Status bar displays live route count; per-route discovery logging can be suppressed with --router-quiet (or GUI "Quiet router logging").

When combined with hook scripts you can trigger in-app navigation (e.g., open menus) and let interception collect subsequent states.

Hook script skeleton:

```python
# spa_tweaks.py
def on_page(page, url, context):
  # Example: wait for critical selector, dismiss cookie banner, expand accordion
  page.wait_for_selector('#root', timeout=5000)
  try:
    banner = page.query_selector('#cookie-accept')
    if banner: banner.click()
  except Exception:
    pass
```

Captured API responses live separately from HTML; you can diff them, replay them, or feed them into other tooling.

Limitations & Notes:

- Prerender is breadth-first link discovery via anchors only (no router event interception yet).
- Client-side navigation triggered without `<a>` elements (e.g., button handlers) may need a hook script to enqueue additional URLs.
- Large SPAs may need an increased `--prerender-max-pages` or targeted hook logic.
- If Playwright isn't installed, the step is skipped with a warning; the static wget2 mirror still succeeds.

## Troubleshooting

- **Missing dependencies**: Use the GUI "Fix Dependencies…" button for install / view commands.
- **Playwright not found**: Install it (`pip install playwright && playwright install chromium`) or disable prerender.
- **Permission denied (Linux)**: Add your user to the `docker` group, then re-login (`newgrp docker`).
- **Port in use**: You'll be prompted to choose another or the run will fail-fast.
- **Slow or incomplete SPA content**: Increase `--prerender-max-pages` and/or add waits in a hook script.
- **Authentication needed for dynamic assets**: Use browser cookies or HTTP auth before prerender.
- **Cloning interrupted**: Re-run with same output and wget2 will resume.
- **Icons not visible**: Place `web_logo.png`, `arrow_right.png`, `docker_logo.png` under `./images/` or alongside the script.

---

## Roadmap

Short-Term:

- Improved error classification & actionable retry hints
- GUI indicators for Playwright availability + install shortcut (basic disable state present; richer guidance TBD)

Dynamic Site Enhancements (Next Iterations):

- Client-side router interception (pushState / history API) for deeper SPA traversal
- Automatic discovery of JS-triggered navigations (e.g., buttons) via heuristic event hooking
- Snapshot diffing to detect meaningful DOM changes before writing
- Form autofill + scripted auth templates (beyond manual cookie import)

Longer-Term:

- Pluggable post-process pipeline (minify, hash, integrity attributes)
- Incremental update mode (update only changed pages/assets)
- Export to static hosting manifests (Netlify, Vercel rewrites)

---

## Credits

- **Nginx** (Alpine), **Docker**, **wget2**, **PySide6**, **browser_cookie3**, **Playwright**

---

## Author

Randy Northrup
