import os, sys, tempfile, shutil, json
import types

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site

class DummyCallbacks(cw2dt_core.CloneCallbacks):
    def __init__(self): self._log=[]
    def log(self, message: str): self._log.append(message)
    def phase(self, phase: str, pct: int): pass
    def bandwidth(self, rate: str): pass


def test_manifest_contains_api_alias_and_note():
    tmp = tempfile.mkdtemp(prefix='cw2dt_alias_')
    try:
        # Monkeypatch wget2 + prerender to avoid external deps
        def _fake_wget(cmd, cb):
            # Simulate mirrored structure with index.html
            out_idx = os.path.join(cfg.dest, cfg.docker_name, 'index.html')
            os.makedirs(os.path.dirname(out_idx), exist_ok=True)
            with open(out_idx,'w',encoding='utf-8') as f: f.write('<html>Test</html>')
            # Mark clone phase 100%
            if cb:
                try: cb('clone',100)
                except Exception: pass
            return True
        def _fake_prerender(**kwargs):
            # Return zero captures to trigger api_capture_note path
            return {'pages_processed':0,'routes_discovered':0,'api_captured':0}
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        cw2dt_core._wget2_progress = _fake_wget  # type: ignore
        cw2dt_core._run_prerender = lambda *a, **k: _fake_prerender()  # type: ignore
        # Build config enabling prerender + capture_api
        global cfg
        cfg = CloneConfig(
            url='http://example.test', dest=tmp, docker_name='site', build=False,
            jobs=1, bind_ip='127.0.0.1', host_port=8080, container_port=80,
            prerender=True, capture_api=True, router_intercept=True,
            checksums=False, verify_after=False, incremental=False, diff_latest=False,
            plugins_dir=None, json_logs=False, profile=False, open_browser=False,
            run_built=False, serve_folder=False, estimate_first=False
        )
        setattr(cfg, 'cleanup', False)
        res = clone_site(cfg, DummyCallbacks())
        assert res.success, 'Clone should succeed in mocked environment'
        manifest_path = os.path.join(res.output_folder, 'clone_manifest.json')
        assert os.path.exists(manifest_path), 'Manifest missing'
        data = json.load(open(manifest_path,'r',encoding='utf-8'))
        # Alias parity
        assert 'capture_api' in data
        assert 'api_capture' in data
        assert data['capture_api'] == data['api_capture'] == True
        # API capture note for zero captures
        assert data.get('api_capture_note','').startswith('API capture enabled but no JSON'), data.get('api_capture_note')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
