import os, sys, tempfile, shutil

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site


class CB(cw2dt_core.CloneCallbacks):
    def log(self, message: str): pass


def test_incremental_first_run_no_diff_summary():
    tmp = tempfile.mkdtemp(prefix='cw2dt_incr_first_')
    try:
        cw2dt_core.is_wget2_available=lambda: True  # type: ignore
        def _wget_stub(cmd, cb):
            root=os.path.join(cfg.dest,cfg.docker_name); os.makedirs(root,exist_ok=True)
            open(os.path.join(root,'index.html'),'w').write('<html></html>'); return True
        cw2dt_core._wget2_progress=_wget_stub  # type: ignore
        cfg = CloneConfig(url='http://incr.local', dest=tmp, docker_name='site', incremental=True, diff_latest=True)
        setattr(cfg,'cleanup', False)
        res = clone_site(cfg, CB())
        assert res.success
        # First run: no previous state so diff_summary should be None
        assert res.diff_summary is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
