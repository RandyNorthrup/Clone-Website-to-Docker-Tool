---
name: "Feature: Plugin Hooks"
about: Introduce pluggable lifecycle hooks (pre_download, post_asset, finalize)
labels: enhancement, priority-high
---

# Plugin Hooks

## Summary

Expose extension points to transform assets and augment manifests without modifying core.

## Goals


- Discover `.py` files in `--plugins-dir`.
- Support hooks: `pre_download(url, ctx) -> (allow,url)` (future), `post_asset(path, bytes, ctx) -> bytes|None`, `finalize(project_dir, manifest, ctx)`.
- Provide context object with run metadata and diff summary.
- Safely ignore plugin exceptions (warn only).

## Acceptance Criteria


- Sample plugin repository demonstrates HTML rewrite.
- Manifest mutated via finalize reflects in saved file.
- Errors in one plugin do not halt others.

## Non-Goals


- Sandboxing / untrusted execution isolation.

## Implementation Sketch


- Already partially scaffolded (post_asset, finalize).
- Add pre_download placeholder for future wget2 wrapper or alternate fetcher.
- Document plugin API version in README.

## Risks


- Malicious plugin code (document trust model).

## References

ROADMAP: Section 4 – Priority ⭐
