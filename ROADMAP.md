# Clone Website to Docker Tool – Roadmap & Enhancement Backlog

Last updated: 2025-09-30

This document tracks strategic enhancements to evolve the tool beyond its current cloning + prerender + Docker packaging feature set. Items are grouped by domain and tagged with priority & rough effort.

Legend:

- **Priority**: ⭐ (high leverage / near-term), ◼ (medium), △ (optional / longer-term)
- **Effort (est.)**: S (≤1 day), M (1–3 days), L (multi‑day / multi‑feature)

---
 
## 1. Cloning & Content Acquisition

| Feature | Priority | Effort | Notes |
|---------|----------|--------|-------|
| Incremental / delta clone (skip unchanged, optional prune) | ⭐ | M | Store (path,size,mtime,hash) in manifest cache; reuse to avoid re-downloads. |
| Smart crawl strategy (link ranking & filtering) | ⭐ | M | Pattern allow/deny; heuristics for depth & directory weighting. |
| WARC archival export | ◼ | M | Enables archival tooling / replay; parallel to folder output. |
| API freeze mode (stub dynamic API calls) | ◼ | M | Capture JSON responses + inject fetch() patch for offline. |
| HAR / trace capture option | ◼ | S | `--prerender-trace`; writes Playwright trace / HAR. |
| Service worker & cache enumeration | △ | M | Inject script to list registration + caches. |

## 2. Dynamic Rendering / SPA

| Feature | Priority | Effort | Notes |
|---------|----------|--------|-------|
| DOM stability detector (mutation quiet period) | ⭐ | S | Avoid snapshotting half-rendered pages. |
| Lazy-load trigger (scroll / intersection simulation) | ◼ | M | Improves completeness of image/media capture. |
| Route parameter sampling (ID pattern inference) | ◼ | M | Expand limited param-based pages w/out explosion. |
| Enhanced router interception heuristics | △ | L | Detect synthetic navigation (button handlers). |

## 3. Performance & Profiling

| Feature | Priority | Effort | Notes |
|---------|----------|--------|-------|
| Adaptive parallelism (dynamic `-j` tuning) | ⭐ | M | Monitor throughput & error rate; adjust jobs. |
| Parallel checksum hashing + cache | ⭐ | S | Thread pool + skip unchanged by mtime/size. |
| Structured JSON logs (`--json-logs`) | ⭐ | S | Machine-readable events for pipelines. |
| Live incremental manifest writing | ◼ | S | Enables mid-run introspection / partial recovery. |
| Enhanced profiler output (throughput, error rates) | ◼ | S | Extend existing `--profile` JSON. |

## 4. Architecture & Extensibility

| Feature | Priority | Effort | Notes |
|---------|----------|--------|-------|
| Config file support (`--config file.{yml,toml}`) | ⭐ | S | Merge with CLI arguments; GUI export/import. |
| Plugin hooks (pre_download, post_asset, finalize) | ⭐ | M | Simple discovery (plugins/ or entry points). |
| Modular code split (core/, prerender/, docker/, ui/) | ◼ | L | Improves testability & maintainability. |
| REST daemon mode (`serve-api`) | △ | L | Accept JSON jobs; queue & monitor. |

## 5. Integrity, Diff & Auditing

| Feature | Priority | Effort | Notes |
|---------|----------|--------|-------|
| Historical snapshot diff (`--diff-latest`) | ⭐ | S | Report added/removed/modified with hashes. |
| Visual DOM diff (normalized HTML) | △ | M | Strip volatile tokens & compare. |
| Integrity header/security hardening set (`--harden`) | ◼ | S | Add HSTS, XFO, CT, Referrer-Policy, etc. |
| Subresource Integrity generation (optional) | △ | M | Hash scripts/styles; inject `integrity=` attrs. |

## 6. Docker & Deployment

| Feature | Priority | Effort | Notes |
|---------|----------|--------|-------|
| Multi-stage image layering (content/runtime) | ◼ | M | Smaller updates (content layer only). |
| Multi-arch build support (`--docker-buildx`) | ◼ | S | Buildx invocation if available. |
| One-step deploy helpers (S3 / Netlify / CF Pages) | △ | M | Wrap provider CLIs if present. |

## 7. UX & Developer Experience

| Feature | Priority | Effort | Notes |
|---------|----------|--------|-------|
| Saved GUI profiles (Static / Dynamic / Hardened) | ⭐ | S | Rapid preset switching. |
| Inline route/asset filter preview | ◼ | M | Live matching sample list beside regex fields. |
| One-click dependency install buttons | ◼ | S | Playwright / wget2 / Docker guidance. |
| GUI profiling export toggle | ◼ | S | Same JSON profile as headless. |

## 8. Reliability & Recovery

| Feature | Priority | Effort | Notes |
|---------|----------|--------|-------|
| Retry failed-only list (`failed_urls.txt`) | ⭐ | S | Fast reattempt without full resume scan. |
| Circuit breaker (pause on sustained 4xx/5xx) | ◼ | M | Adaptive error backoff. |
| Per-request timeout overrides | ◼ | S | Avoid indefinite stalls on large dynamic assets. |

## 9. Security & Compliance

| Feature | Priority | Effort | Notes |
|---------|----------|--------|-------|
| Respect robots.txt flag (opt-in) | ◼ | S | Ethical crawling mode. |
| PII pattern scan report | △ | M | Basic regex detectors for audits. |
| Secret / token scrubber in logs | ◼ | S | Redact query params & headers. |

## 10. Content Post-Processing

| Feature | Priority | Effort | Notes |
|---------|----------|--------|-------|
| HTML / CSS / JS minification pipeline | ◼ | M | Optional post clone/prerender. |
| Search index build (Lunr / MiniSearch) | ◼ | M | Offline site search capability. |
| Asset hashing & revisioned references | △ | L | Cache-busting & integrity improvements. |

## 11. Packaging & Distribution

| Feature | Priority | Effort | Notes |
|---------|----------|--------|-------|
| PyPI package + console script entry point | ⭐ | M | `pip install cw2dt` usability. |
| Optional extras: `[gui]`, `[prerender]` | ◼ | S | Extras manage dependency surfaces. |
| Auto-update notification (GitHub release check) | △ | S | Background version compare. |

## 12. Observability & Metrics

| Feature | Priority | Effort | Notes |
|---------|----------|--------|-------|
| Metrics JSON (`--metrics-out`) | ⭐ | S | Aggregated counters separate from profile. |
| Crawl graph export (DOT / HTML) | △ | M | Visualization & analysis. |
| Per-phase retry/error counters | ◼ | S | Feed into diff & regression tracking. |

---
 
## Immediate Implementation Path (Suggested Order)

1. Config file support + GUI export/import.
2. Incremental clone + manifest cache (introduce checksum DB or lightweight LMDB/sqlite).
3. Plugin hook system (document API; sample plugin).
4. Snapshot diff command (`--diff-latest`).
5. Structured JSON logging + extended `--profile` fields.

## Data Structures (Drafts)

### Incremental Cache Record

```json
{
  "path": "assets/img/logo.png",
  "size": 12345,
  "mtime": 1696000123,
  "sha256": "abc123..."
}
```

### Diff Output

```json
{
  "added": ["new/page.html"],
  "removed": ["old/obsolete.js"],
  "modified": [
    {"path": "index.html", "old_hash": "...", "new_hash": "...", "delta_bytes": 512}
  ],
  "unchanged_count": 1423
}
```

## Hook Interface (Proposed)

```python
# plugins/example_plugin.py

def pre_download(url, ctx):
    # Return (allow: bool, url_or_new)
    if 'tracking' in url:
        return False, url
    return True, url

def post_asset(path, data: bytes, ctx):
    if path.endswith('.html'):
        data = data.replace(b'<title>', b'<title>[MIRRORED] ')
    return data

def finalize(project_dir, manifest, ctx):
    # Manifest is mutable; can append custom fields
    manifest['custom_note'] = 'Processed by example plugin'
```

`ctx` could provide: `start_url`, `run_id`, `timestamp`, `options`, and shared scratch map.

---
 
## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Feature creep delays delivery | Time-box phases; ship vertical slices (config + incremental + diff). |
| Performance regression with hooks | Benchmark baseline; add lightweight timing per hook (optional). |
| Plugin sandboxing (arbitrary code) | Document trust model; optional `--plugins-safe-mode` to disable. |
| Large manifest growth | Compress large checksum sections or move to sqlite. |

## Open Questions

- Do we need a formal schema version for manifest & diff outputs now? (Recommended: add `"schema": 1`.)
- Where to store incremental cache? (`.cw2dt/state.json` vs sqlite).
- Should diff output integrate into README automatically or remain standalone?

---
 
## Changelog Tracking

Add an entry here when roadmap items are implemented:

| Date | Item | Notes |
|------|------|-------|
| 2025-09-30 | Initial roadmap file | Established prioritization & structure. |

---
End of document.
