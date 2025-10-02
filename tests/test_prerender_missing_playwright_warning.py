import os, sys, tempfile, shutil, json

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site


class CB(cw2dt_core.CloneCallbacks):
    def log(self, message: str): pass


def test_prerender_missing_playwright_emits_manifest_warning():
    tmp = tempfile.mkdtemp(prefix='cw2dt_pw_missing_')
    prev_env = os.environ.get('CW2DT_FORCE_NO_PLAYWRIGHT')
    try:
        # Force prerender path to simulate missing playwright regardless of actual installation
        os.environ['CW2DT_FORCE_NO_PLAYWRIGHT'] = '1'
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        def _wget_stub(cmd, cb):
            root = os.path.join(cfg.dest, cfg.docker_name)
            os.makedirs(root, exist_ok=True)
            open(os.path.join(root,'index.html'),'w').write('<html></html>')
            return True
        cw2dt_core._wget2_progress = _wget_stub  # type: ignore
        # Ensure import fails by removing modules if present
        for m in list(sys.modules.keys()):
            if m.startswith('playwright'):
                del sys.modules[m]
        cfg = CloneConfig(url='http://nopw.local', dest=tmp, docker_name='site', prerender=True)
        setattr(cfg,'cleanup', False)
        res = clone_site(cfg, CB())
        assert res.success
        data = json.load(open(os.path.join(res.output_folder,'clone_manifest.json'),'r',encoding='utf-8'))
        warnings = data.get('warnings') or []
        assert any('Playwright not installed' in w for w in warnings), warnings
    finally:
        if prev_env is not None:
            os.environ['CW2DT_FORCE_NO_PLAYWRIGHT'] = prev_env
        else:
            os.environ.pop('CW2DT_FORCE_NO_PLAYWRIGHT', None)
        shutil.rmtree(tmp, ignore_errors=True)
