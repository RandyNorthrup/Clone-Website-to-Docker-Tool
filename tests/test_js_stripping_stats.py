import os, sys, tempfile, shutil, json

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site

class CB(cw2dt_core.CloneCallbacks):
    def log(self, message: str): pass


def test_js_stripping_stats_present():
    tmp = tempfile.mkdtemp(prefix='cw2dt_js_')
    try:
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        def _wget_stub(cmd, cb):
            root = os.path.join(cfg.dest, cfg.docker_name)
            os.makedirs(root, exist_ok=True)
            # include a script tag to trigger stripping
            open(os.path.join(root,'index.html'),'w',encoding='utf-8').write('<html><head><script src="a.js"></script><script>console.log(1)</script></head><body>Hi</body></html>')
            open(os.path.join(root,'a.js'),'w',encoding='utf-8').write('console.log(1)')
            if cb:
                if callable(cb):
                    cb('clone',100)
                elif hasattr(cb,'progress'):
                    cb.progress('clone',100)
            return True
        cw2dt_core._wget2_progress = _wget_stub  # type: ignore
        cfg = CloneConfig(url='http://e', dest=tmp, docker_name='jsstrip', build=False, jobs=1,
                          bind_ip='127.0.0.1', host_port=8080, container_port=80,
                          prerender=False, capture_api=False,
                          checksums=False, verify_after=False, incremental=False, diff_latest=False,
                          disable_js=True, json_logs=False, profile=False, open_browser=False,
                          run_built=False, serve_folder=False, estimate_first=False)
        setattr(cfg,'cleanup', False)
        res = clone_site(cfg, CB())
        assert res.success
        mpath = os.path.join(res.output_folder,'clone_manifest.json')
        data = json.load(open(mpath,'r',encoding='utf-8'))
        jsstats = data.get('js_stripping') or {}
        # Expect counts based on current implementation keys: html_files, modified
        assert jsstats.get('html_files',0) >= 1, jsstats
        assert jsstats.get('modified',0) >= 1, jsstats
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
