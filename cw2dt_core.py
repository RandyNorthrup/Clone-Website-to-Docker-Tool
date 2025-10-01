"""Core headless-exported helpers extracted from cw2dt for unit tests without Qt dependency."""
from __future__ import annotations
import os, hashlib, json
from datetime import datetime, timezone

# Import selected helpers from main module if available, else redefine minimal ones.
try:
    from cw2dt import (
        compute_checksums, _snapshot_file_hashes, _compute_diff,
        parse_verification_summary, run_verification, validate_required_fields,
        _load_config_file
    )  # type: ignore
except Exception:  # Fallback minimal definitions if the heavy module fails (should not normally happen).
    def compute_checksums(base_folder: str, extra_extensions=None, progress_cb=None, chunk_size: int = 65536):
        extra_ext = [e.lower().lstrip('.') for e in (extra_extensions or []) if e]
        extra_ext_tuple = tuple(f'.{e}' for e in extra_ext)
        results = {}
        for root, _, files in os.walk(base_folder):
            norm_root = root.replace('\\','/')
            is_api = '/_api/' in (norm_root + '/')
            for fn in files:
                low = fn.lower()
                if low.endswith(('.html','.htm')) or (is_api and low.endswith('.json')) or (extra_ext_tuple and low.endswith(extra_ext_tuple)):
                    p = os.path.join(root, fn)
                    rel = os.path.relpath(p, base_folder)
                    h = hashlib.sha256()
                    with open(p,'rb') as f:
                        for chunk in iter(lambda: f.read(chunk_size), b''):
                            h.update(chunk)
                    results[rel] = h.hexdigest()
        return results
    def _snapshot_file_hashes(base: str, extra_ext=None):
        snaps = {}
        exts = set(e.lower().lstrip('.') for e in (extra_ext or []))
        for root, _, files in os.walk(base):
            for fn in files:
                low = fn.lower()
                if low.endswith(('.html','.htm')) or any(low.endswith('.'+e) for e in exts):
                    p = os.path.join(root, fn)
                    rel = os.path.relpath(p, base)
                    h = hashlib.sha256();
                    with open(p,'rb') as f:
                        for chunk in iter(lambda: f.read(65536), b''):
                            h.update(chunk)
                    st = os.stat(p)
                    snaps[rel] = {'sha256': h.hexdigest(),'size': st.st_size,'mtime': int(st.st_mtime)}
        return snaps
    def _compute_diff(prev, curr):
        pf = prev.get('files', {}) if isinstance(prev, dict) else {}
        cf = curr.get('files', {}) if isinstance(curr, dict) else {}
        added = [p for p in cf if p not in pf]
        removed = [p for p in pf if p not in cf]
        modified = []
        unchanged = 0
        for p, meta in cf.items():
            if p in pf:
                if pf[p].get('sha256') != meta.get('sha256'):
                    modified.append({'path': p})
                else:
                    unchanged += 1
        return {'added': added,'removed': removed,'modified': modified,'unchanged_count': unchanged,'total_current': len(cf)}
    def parse_verification_summary(text: str):
        return {'ok':None,'missing':None,'mismatched':None,'total':None}
    def run_verification(manifest_path: str, fast: bool=True, docker_name=None, project_dir=None, readme: bool=True, output_cb=None):
        return False, {'ok':None,'missing':None,'mismatched':None,'total':None}
    def validate_required_fields(url, dest, ip_text, build_docker, docker_name):
        errs=[]
        if not (url or '').strip(): errs.append('Website URL required')
        if not (dest or '').strip(): errs.append('Destination Folder required')
        if not (ip_text or '').strip(): errs.append('Bind IP invalid')
        if build_docker and not (docker_name or '').strip(): errs.append('Docker image name required when building')
        return errs
    def _load_config_file(path: str):
        if not path or not os.path.exists(path): return {}
        with open(path,'r',encoding='utf-8') as f:
            try: return json.load(f)
            except Exception: return {}

__all__ = [
    'compute_checksums','_snapshot_file_hashes','_compute_diff','parse_verification_summary',
    'run_verification','validate_required_fields','_load_config_file'
]
