import os, sys, tempfile, shutil, json

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site


class CB(cw2dt_core.CloneCallbacks):
    def log(self, message: str): pass


def test_router_allow_deny_without_intercept_warns():
    tmp = tempfile.mkdtemp(prefix='cw2dt_routerwarn_')
    try:
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        def _wget_stub(cmd, cb):
            root = os.path.join(cfg.dest, cfg.docker_name)
            os.makedirs(root, exist_ok=True)
            open(os.path.join(root,'index.html'),'w').write('<html></html>')
            return True
        cw2dt_core._wget2_progress = _wget_stub  # type: ignore
        cfg = CloneConfig(url='http://rw.local', dest=tmp, docker_name='site', router_allow=['/api'], router_deny=['/x'], prerender=False)
        setattr(cfg,'cleanup', False)
        res = clone_site(cfg, CB())
        assert res.success
        data = json.load(open(os.path.join(res.output_folder,'clone_manifest.json'),'r',encoding='utf-8'))
        warnings = data.get('warnings') or []
        assert any('allow/deny provided without --router-intercept' in w for w in warnings), warnings
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
