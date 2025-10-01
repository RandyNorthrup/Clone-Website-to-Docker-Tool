#!/usr/bin/env python3
"""Verify checksums recorded in clone_manifest.json.

Usage:
  python verify_checksums.py --manifest /path/to/clone_manifest.json [--fast-missing]

Exits 0 if all present files match and no mismatches. Non‑zero otherwise.
"""
from __future__ import annotations
import argparse, json, os, sys, hashlib


def hash_file(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description='Verify recorded SHA256 checksums against current files')
    p.add_argument('--manifest', required=True, help='Path to clone_manifest.json')
    p.add_argument('--fast-missing', action='store_true', help='Skip hashing files that are missing (just report)')
    args = p.parse_args(argv)

    if not os.path.exists(args.manifest):
        print(f"[error] Manifest not found: {args.manifest}")
        return 2
    with open(args.manifest, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    checks = manifest.get('checksums_sha256')
    if not checks:
        print('[warn] No checksums_sha256 section in manifest; nothing to verify.')
        return 1
    root = manifest.get('output_folder') or os.path.dirname(os.path.abspath(args.manifest))
    missing = []
    mismatched = []
    ok = 0
    total = len(checks)
    for idx, (rel, expected) in enumerate(checks.items(), 1):
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            missing.append(rel)
            if args.fast_missing:
                continue
            else:
                # still attempt to hash -> will yield None
                pass
        actual = hash_file(path)
        if actual is None:
            missing.append(rel)
        elif actual != expected:
            mismatched.append(rel)
        else:
            ok += 1
        if idx == 1 or idx == total or idx % 200 == 0:
            pct = int(idx * 100 / total)
            print(f"[verify] {idx}/{total} ({pct}%)")
    print(f"[verify] OK={ok} Missing={len(missing)} Mismatched={len(mismatched)} Total={total}")
    if missing:
        print('\nMissing files:')
        for m in missing[:25]:
            print('  ', m)
        if len(missing) > 25:
            print(f"  ... (+{len(missing)-25} more)")
    if mismatched:
        print('\nMismatched files:')
        for m in mismatched[:25]:
            print('  ', m)
        if len(mismatched) > 25:
            print(f"  ... (+{len(mismatched)-25} more)")
    return 0 if (ok == total and not missing and not mismatched) else 3


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
