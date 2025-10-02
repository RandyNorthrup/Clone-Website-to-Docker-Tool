import os, sys, tempfile, shutil

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site


class CB(cw2dt_core.CloneCallbacks):
    def log(self, message: str): pass


# We'll capture current cfg via a closure inside each test rather than referencing a global
def _make_wget_stub(cfg_ref):
    def _stub(cmd, cb):
        root = os.path.join(cfg_ref.dest, cfg_ref.docker_name)
        os.makedirs(root, exist_ok=True)
        open(os.path.join(root,'index.html'),'w').write('<html></html>')
        return True
    return _stub


def test_cleanup_without_successful_build_removes_only_nginx():
    tmp = tempfile.mkdtemp(prefix='cw2dt_cleanup_')
    try:
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        # Force docker unavailable so build skipped
        cw2dt_core.docker_available = lambda : False  # type: ignore
        cfg = CloneConfig(url='http://cleanup.local', dest=tmp, docker_name='site', build=False)
        cw2dt_core._wget2_progress = _make_wget_stub(cfg)  # type: ignore
        setattr(cfg,'cleanup', True)
        clone_site(cfg, CB())
        out_dir = os.path.join(tmp,'site')
        assert not os.path.exists(os.path.join(out_dir,'nginx.conf')), 'nginx.conf should be removed'
        # Dockerfile should remain because build not successful and code removes only nginx if build=False
        assert os.path.exists(os.path.join(out_dir,'Dockerfile'))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cleanup_after_successful_build_removes_dockerfile_and_nginx():
    tmp = tempfile.mkdtemp(prefix='cw2dt_cleanup_build_')
    try:
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        cfg = CloneConfig(url='http://cleanup.local', dest=tmp, docker_name='site', build=True)
        cw2dt_core._wget2_progress = _make_wget_stub(cfg)  # type: ignore
        cw2dt_core.docker_available = lambda : True  # type: ignore
        cw2dt_core._cli_run_stream = lambda cmd: 0  # type: ignore (successful build)
        setattr(cfg,'cleanup', True)
        clone_site(cfg, CB())
        out_dir = os.path.join(tmp,'site')
        assert not os.path.exists(os.path.join(out_dir,'nginx.conf'))
        assert not os.path.exists(os.path.join(out_dir,'Dockerfile'))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
