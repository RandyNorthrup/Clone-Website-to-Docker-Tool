import os, sys, tempfile, shutil, json

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site


class CB(cw2dt_core.CloneCallbacks):
    def log(self, message: str): pass


def test_combined_api_graphql_storage_counts():
    tmp = tempfile.mkdtemp(prefix='cw2dt_combined_')
    try:
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        def _wget_stub(cmd, cb):
            root = os.path.join(cfg.dest, cfg.docker_name)
            os.makedirs(root, exist_ok=True)
            open(os.path.join(root,'index.html'),'w').write('<html></html>')
            return True
        cw2dt_core._wget2_progress = _wget_stub  # type: ignore
        cw2dt_core._run_prerender = lambda **k: {  # type: ignore
            'pages_processed': 2,
            'routes_discovered': 0,
            'api_captured': 4,
            'storage_captured': 2,
            'graphql_captured': 3,
            'scroll_passes': 0,
            'dom_stable_pages': 0,
            'dom_stable_total_wait_ms': 0,
        }
        cfg = CloneConfig(url='http://combo.local', dest=tmp, docker_name='site', prerender=True,
                          capture_api=True, capture_graphql=True, capture_storage=True)
        setattr(cfg,'cleanup', False)
        res = clone_site(cfg, CB())
        assert res.success
        data = json.load(open(os.path.join(res.output_folder,'clone_manifest.json'),'r',encoding='utf-8'))
        assert data.get('api_captured_count') == 4
        assert data.get('storage_captured_count') == 2
        assert data.get('graphql_captured_count') == 3
        stats = data.get('prerender_stats') or {}
        assert stats.get('api_captured') == 4 and stats.get('graphql_captured') == 3 and stats.get('storage_captured') == 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
