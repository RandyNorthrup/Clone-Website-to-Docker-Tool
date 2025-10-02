import os, sys, tempfile, shutil, json, shlex

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site


class CB(cw2dt_core.CloneCallbacks):
    def log(self, message: str): pass


def test_repro_command_includes_quota_and_throttle():
    tmp = tempfile.mkdtemp(prefix='cw2dt_repro_qt_')
    try:
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        def _wget_stub(cmd, cb):
            root=os.path.join(cfg.dest,cfg.docker_name); os.makedirs(root,exist_ok=True)
            open(os.path.join(root,'index.html'),'w').write('<html></html>'); return True
        cw2dt_core._wget2_progress = _wget_stub  # type: ignore
        cfg = CloneConfig(url='http://qt.local', dest=tmp, docker_name='qt', size_cap='256K', throttle='1M')
        setattr(cfg,'cleanup', False)
        res = clone_site(cfg, CB()); assert res.success
        data=json.load(open(os.path.join(res.output_folder,'clone_manifest.json'),'r',encoding='utf-8'))
        repro=data.get('reproduce_command'); assert repro
        repro_list=repro if isinstance(repro,list) else shlex.split(repro)
        # Since size_cap/throttle are not currently printed as flags (they are always included if set) check presence
        # build command builder adds --size-cap and --throttle when provided
        joined=' '.join(repro_list)
        assert '--size-cap=256K' in joined or any(t.startswith('--size-cap=256K') for t in repro_list)
        assert '--throttle=1M' in joined or any(t.startswith('--throttle=1M') for t in repro_list)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
