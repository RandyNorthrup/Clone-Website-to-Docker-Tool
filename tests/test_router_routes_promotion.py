import os, sys, tempfile, shutil, json

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site


class CB(cw2dt_core.CloneCallbacks):
    def log(self, message: str):
        pass


def test_router_route_promotion_to_manifest():
    tmp = tempfile.mkdtemp(prefix='cw2dt_routerprom_')
    try:
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        def _wget_stub(cmd, cb):
            root = os.path.join(cfg.dest, cfg.docker_name)
            os.makedirs(root, exist_ok=True)
            open(os.path.join(root,'index.html'),'w').write('<html></html>')
            return True
        cw2dt_core._wget2_progress = _wget_stub  # type: ignore
        # Simulate prerender discovering additional routes
        cw2dt_core._run_prerender = lambda **k: {  # type: ignore
            'pages_processed': 2,
            'routes_discovered': 5,
            'api_captured': 0,
            'storage_captured': 0,
            'scroll_passes': 0,
            'dom_stable_pages': 0,
            'dom_stable_total_wait_ms': 0,
            'graphql_captured': 0,
        }
        cfg = CloneConfig(url='http://router.local', dest=tmp, docker_name='router', build=False,
                          prerender=True, router_intercept=True, prerender_max_pages=10)
        setattr(cfg,'cleanup', False)
        res = clone_site(cfg, CB())
        assert res.success
        data = json.load(open(os.path.join(res.output_folder,'clone_manifest.json'),'r',encoding='utf-8'))
        assert data.get('router_intercept') is True
        assert data.get('router_routes') == 5
        stats = data.get('prerender_stats') or {}
        assert stats.get('routes_discovered') == 5
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
