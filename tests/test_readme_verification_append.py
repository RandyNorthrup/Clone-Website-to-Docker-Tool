import os, sys, tempfile, shutil, json

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site, run_verification

class DummyCallbacks(cw2dt_core.CloneCallbacks):
    def log(self, message: str): pass


def test_verification_appends_to_readme():
    tmp = tempfile.mkdtemp(prefix='cw2dt_readme_')
    try:
        # Mock wget2 and disable prerender for speed
        def _fake_wget(cmd, cb):
            idx = os.path.join(cfg.dest, cfg.docker_name, 'index.html')
            os.makedirs(os.path.dirname(idx), exist_ok=True)
            with open(idx,'w',encoding='utf-8') as f: f.write('<html>X</html>')
            if cb:
                if callable(cb):
                    cb('clone',100)
                elif hasattr(cb,'progress'):
                    cb.progress('clone',100)
            return True
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        cw2dt_core._wget2_progress = _fake_wget  # type: ignore
        # Build config with checksums so verification has content
        global cfg
        cfg = CloneConfig(
            url='http://example.test', dest=tmp, docker_name='site', build=False,
            jobs=1, bind_ip='127.0.0.1', host_port=8080, container_port=80,
            prerender=False, capture_api=False,
            checksums=True, verify_after=False, incremental=False, diff_latest=False,
            plugins_dir=None, json_logs=False, profile=False, open_browser=False,
            run_built=False, serve_folder=False, estimate_first=False
        )
        setattr(cfg,'cleanup', False)
        res = clone_site(cfg, DummyCallbacks())
        assert res.success
        manifest_path = os.path.join(res.output_folder, 'clone_manifest.json')
        data = json.load(open(manifest_path,'r',encoding='utf-8'))
        assert 'checksums_sha256' in data
        # Now run verification (fast) and ensure README gets appended section
        readme_path = os.path.join(res.output_folder, 'README_site.md')
        assert os.path.exists(readme_path)
        before = open(readme_path,'r',encoding='utf-8').read()
        assert 'Verification Result' not in before
        passed, stats = run_verification(manifest_path, fast=True, docker_name='site', project_dir=res.output_folder, readme=True)
        assert passed
        after = open(readme_path,'r',encoding='utf-8').read()
        assert '### Verification Result' in after
        assert 'Passed (' in after or 'Passed\n' in after
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
