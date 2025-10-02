import os, sys, tempfile, shutil, json, shlex

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site


class CB(cw2dt_core.CloneCallbacks):
    def log(self, message: str):
        pass


def test_repro_includes_dom_and_graphql_flags():
    """Ensure new fidelity flags (--dom-stable-ms / --dom-stable-timeout-ms / --capture-graphql) appear in reproduce_command."""
    tmp = tempfile.mkdtemp(prefix='cw2dt_reprodg_')
    try:
        # Monkeypatch external heavy bits
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        def _wget_stub(cmd, cb):
            root = os.path.join(cfg.dest, cfg.docker_name)
            os.makedirs(root, exist_ok=True)
            open(os.path.join(root,'index.html'),'w',encoding='utf-8').write('<html></html>')
            return True
        cw2dt_core._wget2_progress = _wget_stub  # type: ignore
        # Stub prerender to avoid Playwright dependency; just return stats referencing new fields
        cw2dt_core._run_prerender = lambda **k: {  # type: ignore
            'pages_processed': 1,
            'routes_discovered': 0,
            'api_captured': 0,
            'scroll_passes': k.get('scroll_passes',0),
            'dom_stable_pages': 1 if k.get('dom_stable_ms') else 0,
            'dom_stable_total_wait_ms': k.get('dom_stable_ms',0),
            'graphql_captured': 2 if k.get('capture_graphql') else 0,
        }
        cfg = CloneConfig(
            url='http://example.com', dest=tmp, docker_name='dg', build=False,
            prerender=True, prerender_max_pages=5,
            dom_stable_ms=750, dom_stable_timeout_ms=5000,
            capture_graphql=True,
        )
        setattr(cfg,'cleanup', False)
        res = clone_site(cfg, CB())
        assert res.success
        mpath = os.path.join(res.output_folder,'clone_manifest.json')
        data = json.load(open(mpath,'r',encoding='utf-8'))
        repro = data.get('reproduce_command'); assert repro
        repro_list = repro if isinstance(repro, list) else shlex.split(repro)
        joined = ' '.join(repro_list)
        assert '--dom-stable-ms=750' in joined or any(t.startswith('--dom-stable-ms=750') for t in repro_list)
        assert ('--dom-stable-timeout-ms=5000' in joined) or any(t.startswith('--dom-stable-timeout-ms=5000') for t in repro_list)
        assert '--capture-graphql' in repro_list or any(t.startswith('--capture-graphql') for t in repro_list)
        # Manifest promoted fields should exist
        assert data.get('capture_graphql') is True
        assert data.get('prerender_scroll_passes') == 0
        assert data.get('dom_stable_ms') == 750
        assert data.get('dom_stable_timeout_ms') == 5000
        assert data.get('graphql_captured_count') == 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
