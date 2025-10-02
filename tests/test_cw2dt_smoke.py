"""Smoke tests for modular cw2dt core.

These tests avoid network + docker side effects by:
- Creating a fake mirrored output directory structure.
- Invoking checksum + manifest + verification utilities.
- Exercising incremental state + diff functions.
- Exercising plugin hook loading with a temporary plugin.

They do NOT run wget2 or Playwright; those would be covered by separate
integration tests gated behind environment flags.
"""
from __future__ import annotations

import json, os, tempfile, textwrap, time
from pathlib import Path

import importlib, importlib.util

from cw2dt_core import (
    compute_checksums,
    run_verification,
    parse_verification_summary,
    _snapshot_file_hashes,
    _compute_diff,
    _ensure_state_dir,
    _save_state,
    _load_state,
    _timestamp,
)


def _write(p: Path, content: str, mode: str = 'w'):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding='utf-8')


def test_checksums_and_verification_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'site'
        _write(root / 'index.html', '<html><body><h1>Hi</h1></body></html>')
        _write(root / 'style.css', 'body { color: #333; }')
        # Compute checksums (include css by extension)
        chks = compute_checksums(str(root), ['css'])
        assert 'index.html' in chks and 'style.css' in chks
        # Build manifest
        manifest = {
            'url': 'http://example.test',
            'docker_name': 'site',
            'output_folder': str(root),
            'prerender': False,
            'capture_api': False,
            'router_intercept': False,
            'checksums_included': True,
            'checksum_extra_extensions': ['css'],
            'checksums_sha256': chks,
        }
        manifest_path = root / 'clone_manifest.json'
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        # Run verification (fast)
        passed, stats = run_verification(str(manifest_path), fast=True, docker_name=None, project_dir=str(root), readme=False)
        assert passed, f"Verification failed unexpectedly: {stats}"
        # Tamper with file
        _write(root / 'index.html', '<html><body><h1>Changed</h1></body></html>')
        passed2, stats2 = run_verification(str(manifest_path), fast=True, docker_name=None, project_dir=str(root), readme=False)
        assert not passed2, 'Verification should fail after tamper'
        # Parse a synthetic summary line
        summary = 'OK=10 Missing=2 Mismatched=1 Total=13'
        parsed = parse_verification_summary(summary)
        assert parsed == {'ok':10,'missing':2,'mismatched':1,'total':13}


def test_incremental_state_and_diff():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'site'
        _write(root / 'index.html', 'A')
        _write(root / 'a.txt', 'aaa')
        state_dir = _ensure_state_dir(str(root))
        first = {'schema':1,'timestamp':_timestamp(),'files':_snapshot_file_hashes(str(root))}
        _save_state(str(root), first)
        time.sleep(0.01)
        _write(root / 'a.txt', 'bbbb')
        _write(root / 'b.txt', 'new')
        second = {'schema':1,'timestamp':_timestamp(),'files':_snapshot_file_hashes(str(root))}
        _save_state(str(root), second)
        loaded = _load_state(str(root))
        assert loaded['files'] == second['files']
        diff = _compute_diff(first, second)
        assert 'added' in diff and 'changed' in diff and 'removed' in diff
        assert 'b.txt' in diff['added']
        assert 'a.txt' in diff['changed']


def test_plugin_hook_invocation():
    with tempfile.TemporaryDirectory() as tmp:
        plugdir = Path(tmp) / 'plugins'
        plugdir.mkdir(parents=True, exist_ok=True)
        plugin_code = textwrap.dedent('''\
            events = []
            def pre_download(context):
                events.append(('pre', sorted(context.keys())))
            def post_asset(context):
                events.append(('post', context.get('asset')))
            def finalize(context):
                events.append(('finalize', sorted(context.keys())))
        ''')
        (plugdir / 'sample_plugin.py').write_text(plugin_code, encoding='utf-8')
        # Simulate minimal plugin execution similar to clone_site sequence
        spec = importlib.util.spec_from_file_location('sample_plugin', plugdir / 'sample_plugin.py')
        mod = importlib.util.module_from_spec(spec)  # type: ignore
        assert spec and spec.loader
        spec.loader.exec_module(mod)  # type: ignore
        ctx = {'url':'http://x','output_folder':str(tmp), 'asset':'demo'}
        if hasattr(mod, 'pre_download'): mod.pre_download({'url':ctx['url']})
        if hasattr(mod, 'post_asset'): mod.post_asset({'asset':ctx['asset']})
        if hasattr(mod, 'finalize'): mod.finalize({'output_folder':ctx['output_folder']})
        assert getattr(mod,'events',[]) == [
            ('pre',['url']),
            ('post','demo'),
            ('finalize',['output_folder'])
        ]
