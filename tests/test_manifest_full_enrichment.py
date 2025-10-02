import os, sys, json, tempfile, shutil, time

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site

class CaptureCallbacks(cw2dt_core.CloneCallbacks):
    def __init__(self): self.events=[]; self.logs=[]; self.phases=[]
    def log(self, message: str):
        self.logs.append(message)
        if message.startswith('{') and message.endswith('}'):
            try:
                import json as _j; self.events.append(_j.loads(message))
            except Exception: pass
    def phase(self, phase: str, pct: int): self.phases.append((phase,pct))


def test_full_manifest_enrichment_core_fields():
    tmp = tempfile.mkdtemp(prefix='cw2dt_full_')
    try:
        # Monkeypatch heavy operations
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        def _wget_stub(cmd, cb):
            # Create a small site with two html and one css for richer stats
            root = os.path.join(cfg.dest, cfg.docker_name)
            os.makedirs(root, exist_ok=True)
            open(os.path.join(root,'index.html'),'w').write('<html><h1>Home</h1><script>var x=1;</script></html>')
            open(os.path.join(root,'about.html'),'w').write('<html>About</html>')
            os.makedirs(os.path.join(root,'_api'), exist_ok=True)
            open(os.path.join(root,'_api','data.json'),'w').write('{"x":1}')
            if cb:
                if callable(cb):
                    cb('clone',100)
                elif hasattr(cb,'progress'):
                    cb.progress('clone',100)
            return True
        cw2dt_core._wget2_progress = _wget_stub  # type: ignore
        cw2dt_core.docker_available = lambda : False  # skip build
        cw2dt_core._run_prerender = lambda *a, **k: {'pages_processed':1,'routes_discovered':0,'api_captured':1}  # type: ignore
        cfg = CloneConfig(
            url='http://example.test', dest=tmp, docker_name='site', build=False, jobs=1,
            bind_ip='127.0.0.1', host_port=8100, container_port=8080,
            prerender=True, capture_api=True, router_intercept=False,
            checksums=True, verify_after=True, verify_deep=False,
            incremental=True, diff_latest=True, plugins_dir=None,
            json_logs=True, profile=True, open_browser=False, run_built=False,
            serve_folder=False, estimate_first=True
        )
        setattr(cfg,'cleanup', False)
        cb = CaptureCallbacks()
        res = clone_site(cfg, cb)
        assert res.success
        manifest_path = os.path.join(res.output_folder,'clone_manifest.json')
        data = json.load(open(manifest_path,'r',encoding='utf-8'))
        # Core expected keys / enrichment
        for k in ['started_utc','completed_utc','clone_success','docker_built','prerender','capture_api','api_capture','parallel_jobs','timings','phase_durations_seconds']:
            assert k in data, f"Missing manifest key {k}"
        # Reproduce command present
        assert isinstance(data.get('reproduce_command'), list) and data['reproduce_command'], 'reproduce_command missing'
        # API capture note should indicate success path
        assert 'api_capture_note' in data
        # Checksums present
        assert 'checksums_sha256' in data
        # js stripping not enabled so absent
        assert 'js_stripping' not in data
        # resume section exists
        assert 'resume' in data and isinstance(data['resume'], dict)
        # verification meta elapsed recorded
        if 'verification_meta' in data:
            assert 'elapsed_ms' in data['verification_meta']
        # diff summary object available in result if diff_latest True
        if res.diff_summary:
            assert 'added' in res.diff_summary
        # Ensure timing keys contain clone_seconds
        assert 'clone_seconds' in data['timings']
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
