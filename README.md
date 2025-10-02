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
  - Two‑phase Recommendation Wizard (scan + results apply)
  - Save / Load configuration profiles (reusable loadouts)
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

### Wizard & Profiles

The GUI includes a two‑phase Recommendation Wizard and profile management. The wizard now also evaluates inline JSON data blobs, GraphQL hints, potential REST endpoints, and overall dynamic weight to suggest API / storage capture and integrity options:

#### Phase 1 – Scan

- Performs a lightweight fetch of the root URL (capped ~250KB) and heuristic analysis.
- Detects common SPA frameworks (React, Vue, Angular, Next.js, Nuxt, Svelte), script density, payload size.
- Attempts an item estimate (wget2 spider) when possible.
- Generates human-readable heuristic reasons supporting each recommendation.

#### Phase 2 – Results

- Presents a summary (bytes fetched, script count, frameworks, estimated items, reasons).
- Provides recommendation checkboxes (pre‑toggled when heuristics fire):
  - Prerender (dynamic rendering)
  - Router interception (SPA routes)
  - Capture API JSON (`_api/`)
  - Capture API Binary (PDF / images / octet-stream, etc.)
  - Capture Storage (localStorage + sessionStorage snapshots)
  - Capture GraphQL operations (`_graphql/`)
  - Checksums + verify integrity
  - Incremental + diff state tracking
  - (Optional) JavaScript stripping (not auto‑recommended; you can toggle manually)
- Apply updates the main form; you can still manually tweak afterward.

Profiles:

- Use Save Config to store the current settings as a JSON profile under `~/.cw2dt_profiles/`.
- Use Load Config to quickly recall a prior configuration (e.g., staging vs prod mirror strategies).
- Profile files are human-editable; removing a file removes it from the list.
- Suggested name defaults to the Docker name field; invalid filename characters are sanitized.

Typical Workflow:

1. Enter URL → Run Wizard → Apply.
2. Optionally adjust advanced checkboxes (e.g., hook script or checksum extensions).
3. Save Config for reuse.
4. Clone.

Heuristic Hints (current logic):

- Script count > 15 OR SPA framework marker (React / Vue / Angular / Next / Nuxt / Svelte) → enable prerender.
- Framework marker + dynamic assumption → also enable router interception.
- Very small payload (< 35 KB) AND few scripts (≤ 4) AND no framework → disable prerender (likely static).
- Heavy scripts (> 25) without framework → still treat as dynamic (prerender on).
- Inline JSON/ld+json script tags > 2 OR obvious `/api/` or `.json` references → recommend API JSON capture.
- Very heavy dynamic (scripts > 40 OR inline JSON > 4) → also recommend storage snapshot + binary API capture.
- Presence of the word `graphql` → recommend GraphQL capture.
- Heavy dynamic (scripts > 25 OR payload > ~120 KB) → suggest checksums + incremental for change tracking.
- Any capture flag (API/storage/GraphQL) auto‑forces prerender if you manually disabled it.

The Wizard intentionally keeps the scan shallow for speed; you can still refine settings manually for complex sites.

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
  --size-cap 2G --throttle 4M --max-threads 12 \
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
- Concurrency: Use `--max-threads N` (wget2 2.x). Older builds may only support `--jobs N`. The tool auto-detects the supported flag; in the GUI this appears as "Download Threads".
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
- `--prerender-scroll N` Perform N incremental scroll passes per prerendered page (each pass scrolls to bottom then waits ~350ms) to surface lazy-loaded content (0 disables)
- `--capture-api` Persist application/json responses into `_api/`
- `--capture-api-types TYPES` Capture additional content-types (comma or slash separated). Example: `--capture-api-types application/json,text/csv,application/xml`.
- `--capture-api-binary` Include common binary API responses (pdf, images, audio, video, octet-stream). Saved with inferred or fallback extensions under `_api/`.
- `--capture-storage` Capture `localStorage` + `sessionStorage` snapshot for each prerendered page into `_storage/` mirroring the HTML path with `.storage.json` suffix.
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
5. If `--prerender-scroll` is non-zero, the page is scrolled to the bottom that many times (with short waits) before HTML snapshot to trigger infinite/lazy loading.
6. If `--capture-api` is set, matching API/XHR/fetch responses are stored under `_api/` mirroring the request path. By default only `application/json` is captured. Extend or narrow capture with `--capture-api-types` (comma or slash separated prefixes, e.g. `application/json,text/plain,text/csv`). Add `--capture-api-binary` to also persist common binary types (`application/pdf`, `application/octet-stream`, `image/*`, `audio/*`, `video/*`). Text responses are UTF‑8 written with a mapped extension; binary responses are written verbatim (fallback `.bin`).
7. If `--capture-storage` is enabled, a snapshot of `localStorage` and `sessionStorage` for the page is written under `_storage/` with the same relative path as the HTML file but ending in `.storage.json` (e.g. `about/index.storage.json`).
8. If a `--hook-script` is provided and exports `on_page(page, url, context)`, it is invoked before HTML extraction (ideal for login flows, expanding lazy content, or scraping single-page app states).
9. Unless `--no-url-rewrite` is specified, absolute occurrences of the origin (`https://host`) are rewritten to relative paths for better relocatability inside containers or alternate domains.
10. The prerender queue stops when either the page limit is reached or there are no more same‑origin links/routes to process.
11. (Optional) If `--dom-stable-ms N` is supplied, a lightweight MutationObserver heuristic waits until there has been a quiet window of N milliseconds with no DOM mutations (or the `--dom-stable-timeout-ms` is reached) before snapshotting each page. This helps avoid capturing intermediate loading states in JS-heavy apps.
12. (Optional) If `--capture-graphql` is enabled, GraphQL POST operations are persisted to `_graphql/` as `<operation>-<n>.graphql.json` containing operation name, query, variables, and JSON response.

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
- `--dom-stable-ms N` — require N ms of no DOM mutations before capturing (heuristic stabilization)
- `--dom-stable-timeout-ms M` — maximum additional wait attempting stability per page (default 4000)
- `--capture-graphql` — capture GraphQL operation requests & responses into `_graphql/`

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

- Router interception (history API patching for pushState/replaceState/hashchange/click) is implemented; README earlier versions stated it was future—this has been updated for accuracy.
- Purely programmatic navigations that never alter history or anchor links (e.g., custom in‑memory view swaps) still require a hook script to trigger additional states.
- Infinite scroll or lazy content may need hook-assisted scrolling.
- Large SPAs may need an increased `--prerender-max-pages` or targeted hook logic.
- If Playwright isn't installed, the step is skipped with a warning; the static wget2 mirror still succeeds.

### Maximum Fidelity Mode (Power Profile)

For the closest 1:1 snapshot of a modern SPA (deep navigation + dynamic content), consider enabling:

```bash
python cw2dt.py --headless \
  --url "https://target.example" \
  --dest ./out --docker-name target \
  --max-threads 12 \
  --prerender --prerender-max-pages 120 \
  --router-intercept --router-max-routes 350 --router-settle-ms 900 \
  --capture-api --capture-api-types application/json,text/plain --capture-api-binary --capture-storage \
  --capture-graphql \
  --hook-script ./hooks/fidelity.py \
  --checksums --checksum-ext css,js,png,jpg,svg,json \
  --verify-after --incremental --diff-latest
```

Details:

- `_api/` mirrors the URL path of captured responses. Directory indices (`/path/`) become `path/index.<ext>`.
- Extension mapping heuristics: json -> `.json`, csv -> `.csv`, xml -> `.xml`, graphql -> `.graphql(.json)`, plain -> `.txt`; binary falls back to inferred extension or `.bin`.
- Provide multiple types with either commas or whitespace: `--capture-api-types application/json,text/csv` or `--capture-api-types application/json text/csv`.
- Storage snapshots are per prerendered HTML page; only pages storing data produce a `.storage.json` file.
- Storage files include: `{ "url": <page_url>, "localStorage": {..}, "sessionStorage": {..} }`.
- Checksums include HTML + JSON (and any added extensions). Binary API assets are not hashed unless their extensions are listed.

Recommendations:

- Raise `--prerender-max-pages` gradually (avoid huge first runs).
- Tune `--router-settle-ms` upward for late async route pushes (900–1500ms for heavy frameworks).
- Use `--router-allow` to fence param explosions (`--router-allow "/products/,/docs/"`).
- Author a fidelity hook script to: dismiss cookie banners, expand menus, scroll, click tabs, trigger lazy loads.

Hook script example:

```python
def on_page(page, url, context):
  # Dismiss common overlays
  for sel in ['#cookie-accept', '.cookie-accept', '.modal-close']:
    try:
      btn = page.query_selector(sel)
      if btn: btn.click()
    except Exception:
      pass
  # Expand navigational elements
  for sel in ['.menu-toggle', '.accordion-toggle', '[aria-expanded="false"]']:
    for el in page.query_selector_all(sel)[:15]:
      try: el.click()
      except Exception: pass
  # Simulate incremental scroll to trigger lazy loading
  try:
    for _ in range(6):
      page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
      page.wait_for_timeout(350)
  except Exception:
    pass
  # Click visible tab-like controls
  for sel in ['[role=tab]', '.tab', '.nav-item']:
    for el in page.query_selector_all(sel)[:12]:
      try:
        el.click(); page.wait_for_timeout(180)
      except Exception: continue
```

Performance Caveats:

- Higher page and route caps increase disk + time; iterate to find a sweet spot.
- Avoid enabling power profile for purely static sites—wastes prerender budget.
- Consider a two-pass approach: static baseline first (checksums), then prerender power profile with `--diff-latest` to see added value.


## Troubleshooting

The GUI now includes a dedicated **Troubleshooting** collapsible panel exposing:

1. **User-Agent Override** – Many sites return 403/406/5xx or aggressively throttle when they detect default crawler identifiers. Provide a realistic modern browser UA (e.g. latest Chrome) to improve acceptance.
1. **Extra wget2 Args** – Raw passthrough for advanced tuning (retries, backoff, header overrides). Example:

  ```bash
  --retry-on-http-error=429,500,503 --tries=3 --waitretry=2 --timeout=20
  ```

1. **Diagnose Last Error** – Analyzes the tail of the console log (recent ~80 lines) to detect:

  - wget2 exit codes (2,4,5,6,8)
  - Common HTTP status patterns (403,404,429,503)
  - Missing custom User-Agent / retry/backoff hints

  Suggestions are displayed in a dialog and echoed (summarized) back into the console with `[diag]` prefixes.

Headless equivalents:

```bash
--user-agent "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
--extra-wget-args "--retry-on-http-error=429,500,503 --tries=3 --waitretry=2"
--auto-backoff
--log-redirect-chain
--save-wget-stderr
--insecure            # (diagnostic) ignore TLS cert validation (adds --no-check-certificate)
```

### Common wget2 Exit Codes & Hints

| Code | Meaning (Simplified) | Typical Causes | Recommended Actions |
|------|----------------------|----------------|--------------------|
| 2 | Usage / parse error | Bad extra args, malformed flags | Re-check `--extra-wget-args`, remove one flag at a time |
| 4 | Network failure | DNS issues, transient outages, proxy / firewall interference | Add retries/backoff, verify connectivity, reduce threads |
| 5 | SSL/TLS error | Cert validation failure, protocol mismatch | Confirm HTTPS works in browser, consider (temporary) `--no-check-certificate` for diagnosis only |
|   | (Insecure bypass) | (Diagnostic only) | Use GUI "Ignore TLS Cert" or `--insecure` to confirm cause, then remove and fix chain |
| 6 | Authentication failure | Invalid credentials/cookies | Re-export cookies, verify auth_user/pass, ensure logged-in session still valid |
| 8 | Server error (4xx/5xx bursts) | Bot blocks, rate limiting, anti-scrape, overload | Set realistic UA, lower threads (try 4–6), add retry/backoff (429/500/503), stagger runs |

If several 403 or 503 responses appear early, immediately try a custom User-Agent and a lower thread count. For 429 (Too Many Requests) add `--waitretry` to introduce exponential pauses.

### HTTP Status Patterns

- **403 Forbidden**: Usually mitigated by UA override and/or cookies (logged-in context).
- **404 Not Found**: Confirm start URL; check for base path redirects you may need to include.
- **429 Too Many Requests**: Lower concurrency (`--max-threads 4-6`) + retry/backoff.
- **503 Service Unavailable**: Server load or intentional throttling; combine lower concurrency + retry + delay between runs.

### General Guidance

- **Missing dependencies**: Use the GUI "Dependencies" button for install/view commands.
- **Playwright not found**: Install it (`pip install playwright && playwright install chromium`) or disable prerender.
- **Permission denied (Linux)**: Add your user to the `docker` group, then re-login (`newgrp docker`).
- **Port in use**: Choose another or the run fails fast.
- **Slow or incomplete SPA content**: Increase `--prerender-max-pages`; if infinite scroll, add `--prerender-scroll` and/or a hook script.
- **Authentication needed for dynamic assets**: Use browser cookies or HTTP auth before prerender.
- **Interrupted clone**: Re-run; wget2 resumes.
- **Icons not visible**: Place `web_logo.png`, `arrow_right.png`, `docker_logo.png` under `./images/`.
- **Checksum verification failures**: Use `--verify-deep` to force strict error or inspect individual mismatches in `clone_manifest.json`.
- **Performance tuning**: Start with moderate threads (8–12). If encountering server pressure, dial down.
- **Auto Backoff Retry**: Enable this (GUI checkbox or `--auto-backoff`) to automatically retry once with half the threads and retry/backoff flags after an initial failure.
- **Redirect Chain Logging**: Use `--log-redirect-chain` (or GUI checkbox) to print the resolved redirect path before cloning; useful to detect unexpected domain hops.
- **Save wget stderr**: Enable to persist full low-level wget2 stderr to `wget_stderr.log` inside the output directory for deeper post-mortem.
- **Ignore TLS Cert (insecure)**: Adds `--no-check-certificate` to skip TLS validation purely for diagnosis of exit code 5 issues. Do not leave enabled for normal runs (security risk / MITM exposure).

### When to Use Extra Args

Examples:

| Scenario | Extra Args Example |
|----------|--------------------|
| Rate limiting (429) | `--retry-on-http-error=429,500,503 --tries=4 --waitretry=2` |
| Sporadic TLS timeouts | `--tries=3 --timeout=25` |
| Slow server, need pacing | `--wait=0.5` (introduces 0.5s between retrievals) |
| Debug headers | `--debug` (verbose; trim after diagnosing) |

Avoid piling on too many options first attempt; add incrementally and re-run diagnostics.

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
