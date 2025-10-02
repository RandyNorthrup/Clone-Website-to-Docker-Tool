import os, sys, tempfile, shutil, json

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site

class CB(cw2dt_core.CloneCallbacks):
    def log(self, message: str): pass


def test_cleanup_flag_preserves_site_when_disabled():
    tmp = tempfile.mkdtemp(prefix='cw2dt_clean_')
    try:
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        def _wget_stub(cmd, cb):
            root = os.path.join(cfg.dest, cfg.docker_name)
            os.makedirs(root, exist_ok=True)
            open(os.path.join(root,'index.html'),'w').write('ok')
            if cb:
                if callable(cb):
                    cb('clone',100)
                elif hasattr(cb,'progress'):
                    cb.progress('clone',100)
            return True
        cw2dt_core._wget2_progress = _wget_stub  # type: ignore
        cfg = CloneConfig(url='http://e', dest=tmp, docker_name='clean', build=False, jobs=1,
                          bind_ip='127.0.0.1', host_port=8080, container_port=80,
                          prerender=False, capture_api=False,
                          checksums=False, verify_after=False, incremental=False, diff_latest=False,
                          json_logs=False, profile=False, open_browser=False,
                          run_built=False, serve_folder=False, estimate_first=False)
        setattr(cfg,'cleanup', False)
        res = clone_site(cfg, CB())
        assert res.success
        site_root = os.path.join(res.output_folder)
        assert os.path.exists(os.path.join(site_root,'index.html'))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
