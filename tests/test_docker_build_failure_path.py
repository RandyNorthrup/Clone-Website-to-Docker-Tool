import os, sys, tempfile, shutil, json

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site


class CB(cw2dt_core.CloneCallbacks):
    def log(self, message: str): pass


def test_docker_build_failure_sets_manifest_flags():
    tmp = tempfile.mkdtemp(prefix='cw2dt_buildfail_')
    try:
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        def _wget_stub(cmd, cb):
            root = os.path.join(cfg.dest, cfg.docker_name)
            os.makedirs(root, exist_ok=True)
            open(os.path.join(root,'index.html'),'w').write('<html></html>')
            return True
        cw2dt_core._wget2_progress = _wget_stub  # type: ignore
        cw2dt_core.docker_available = lambda : True  # type: ignore
        cw2dt_core._cli_run_stream = lambda cmd: 99  # type: ignore (failure)
        cfg = CloneConfig(url='http://fail.local', dest=tmp, docker_name='site', build=True)
        setattr(cfg,'cleanup', False)
        res = clone_site(cfg, CB())
        assert res.success, 'Overall clone should still report success despite build failure'
        data = json.load(open(os.path.join(res.output_folder,'clone_manifest.json'),'r',encoding='utf-8'))
        assert data.get('docker_built') is False
        assert data.get('clone_success') is True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
