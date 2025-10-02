import os, sys, tempfile, shutil, json, shlex

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site


class CB(cw2dt_core.CloneCallbacks):
    def log(self, message: str):
        pass


def test_storage_and_api_binary_manifest_and_repro():
    """Validate that storage capture and api binary flags propagate to manifest & reproduction command."""
    tmp = tempfile.mkdtemp(prefix='cw2dt_storebin_')
    try:
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        def _wget_stub(cmd, cb):
            root = os.path.join(cfg.dest, cfg.docker_name)
            os.makedirs(root, exist_ok=True)
            open(os.path.join(root,'index.html'),'w',encoding='utf-8').write('<html></html>')
            return True
        cw2dt_core._wget2_progress = _wget_stub  # type: ignore
        # Stub prerender to simulate storage + api captures
        cw2dt_core._run_prerender = lambda **k: {  # type: ignore
            'pages_processed':1,
            'routes_discovered':0,
            'api_captured':3,
            'storage_captured':2,
            'scroll_passes':k.get('scroll_passes',0),
            'dom_stable_pages':0,
            'dom_stable_total_wait_ms':0,
            'graphql_captured':0,
        }
        cfg = CloneConfig(
            url='http://ex.local', dest=tmp, docker_name='sb', build=False,
            prerender=True, capture_api=True, capture_api_binary=True, capture_storage=True,
            prerender_scroll=2,
            capture_graphql=False
        )
        setattr(cfg,'cleanup', False)
        res = clone_site(cfg, CB())
        assert res.success
        mpath = os.path.join(res.output_folder,'clone_manifest.json')
        data = json.load(open(mpath,'r',encoding='utf-8'))
        # Manifest booleans / counts
        assert data.get('capture_storage') is True
        assert data.get('capture_api_binary') is True
        assert data.get('storage_captured_count') == 2
        assert data.get('api_captured_count') == 3
        assert data.get('prerender_scroll_passes') == 2
        # Reproduction command includes relevant flags
        repro = data.get('reproduce_command'); assert repro
        repro_list = repro if isinstance(repro, list) else shlex.split(repro)
        joined = ' '.join(repro_list)
        assert '--capture-storage' in repro_list
        assert '--capture-api-binary' in repro_list
        assert '--prerender-scroll=2' in joined or any(t.startswith('--prerender-scroll=2') for t in repro_list)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
