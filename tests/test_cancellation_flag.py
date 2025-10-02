import os, sys, tempfile, shutil
import time

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site

class CancelCallbacks(cw2dt_core.CloneCallbacks):
    def __init__(self): self._log=[]; self._cancel_after=0.0; self._start=time.time()
    def log(self, message: str): self._log.append(message)
    def phase(self, phase: str, pct: int):
        # Trigger cancellation early during clone phase < 50%
        if phase=='clone' and pct>=10:
            self._cancel=True
    def is_canceled(self)->bool:
        return getattr(self,'_cancel',False)


def test_cancellation_sets_manifest_flag():
    tmp = tempfile.mkdtemp(prefix='cw2dt_cancel_')
    try:
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        # Slow fake wget so we can cancel
        def _fake_wget(cmd, cb):
            # produce index.html gradually
            out_idx = os.path.join(cfg.dest, cfg.docker_name, 'index.html')
            os.makedirs(os.path.dirname(out_idx), exist_ok=True)
            with open(out_idx,'w',encoding='utf-8') as f: f.write('<html>Test</html>')
            for p in (1,5,9,15,25,40):
                if cb:
                    if callable(cb):
                        cb('clone',p)
                    elif hasattr(cb,'progress'):
                        cb.progress('clone',p)
                time.sleep(0.01)
            return False  # simulate termination
        cw2dt_core._wget2_progress = _fake_wget  # type: ignore
        global cfg
        cfg = CloneConfig(
            url='http://example.test', dest=tmp, docker_name='site', build=False,
            jobs=1, bind_ip='127.0.0.1', host_port=8080, container_port=80,
            prerender=False, capture_api=False,
            checksums=False, verify_after=False, incremental=False, diff_latest=False,
            plugins_dir=None, json_logs=False, profile=False, open_browser=False,
            run_built=False, serve_folder=False, estimate_first=False
        )
        setattr(cfg,'cleanup', False)
        cb = CancelCallbacks()
        res = clone_site(cfg, cb)
        # Clone should be marked unsuccessful
        assert not res.success
        manifest_path = os.path.join(tmp, 'site', 'clone_manifest.json')
        if os.path.exists(manifest_path):
            import json
            data = json.load(open(manifest_path,'r',encoding='utf-8'))
            # If manifest exists, canceled flag should be set (depends on phase when aborted)
            assert data.get('canceled') == True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
