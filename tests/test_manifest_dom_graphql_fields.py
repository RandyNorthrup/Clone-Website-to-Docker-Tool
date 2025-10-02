import os, sys, json, tempfile, shutil

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site


class CB(cw2dt_core.CloneCallbacks):
    def log(self, message: str):
        pass


def test_manifest_includes_dom_and_graphql_fields():
    tmp = tempfile.mkdtemp(prefix='cw2dt_mdg_')
    try:
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        def _wget_stub(cmd, cb):
            root = os.path.join(cfg.dest, cfg.docker_name)
            os.makedirs(root, exist_ok=True)
            open(os.path.join(root,'index.html'),'w').write('<html></html>')
            return True
        cw2dt_core._wget2_progress = _wget_stub  # type: ignore
        cw2dt_core._run_prerender = lambda **k: {  # type: ignore
            'pages_processed':1,
            'routes_discovered':0,
            'api_captured':0,
            'scroll_passes':0,
            'dom_stable_pages':1,
            'dom_stable_total_wait_ms':k.get('dom_stable_ms',0),
            'graphql_captured':1,
        }
        cfg = CloneConfig(url='http://ex.test', dest=tmp, docker_name='site', prerender=True,
                           dom_stable_ms=600, dom_stable_timeout_ms=4000, capture_graphql=True)
        setattr(cfg,'cleanup', False)
        res = clone_site(cfg, CB())
        assert res.success
        mpath = os.path.join(res.output_folder,'clone_manifest.json')
        data = json.load(open(mpath,'r',encoding='utf-8'))
        assert data.get('dom_stable_ms') == 600
        assert data.get('dom_stable_timeout_ms') == 4000
        assert data.get('capture_graphql') is True
        assert data.get('graphql_captured_count') == 1
        stats = data.get('prerender_stats') or {}
        assert 'dom_stable_pages' in stats and 'dom_stable_total_wait_ms' in stats and 'graphql_captured' in stats
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
