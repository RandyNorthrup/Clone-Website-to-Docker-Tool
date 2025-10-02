import os, sys, tempfile, shutil, json, textwrap

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site

class CB(cw2dt_core.CloneCallbacks):
    def log(self, message: str): pass


def test_plugin_finalize_can_modify_manifest():
    tmp = tempfile.mkdtemp(prefix='cw2dt_fin_')
    try:
        plugdir = os.path.join(tmp,'plugins'); os.makedirs(plugdir, exist_ok=True)
        # Plugin only implements finalize hook to add a custom key
        plugin_code = textwrap.dedent('''\
            def finalize(output_folder, manifest, context):
                if isinstance(manifest, dict):
                    manifest['finalize_custom'] = {'added': True}
        ''')
        open(os.path.join(plugdir,'finalize_plug.py'),'w',encoding='utf-8').write(plugin_code)
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        def _wget_stub(cmd, cb):
            root = os.path.join(cfg.dest, cfg.docker_name)
            os.makedirs(root, exist_ok=True)
            open(os.path.join(root,'index.html'),'w').write('<html>F</html>')
            if cb:
                if callable(cb): cb('clone',100)
                elif hasattr(cb,'progress'): cb.progress('clone',100)
            return True
        cw2dt_core._wget2_progress = _wget_stub  # type: ignore
        cfg = CloneConfig(url='http://e', dest=tmp, docker_name='site', build=False, jobs=1,
                          bind_ip='127.0.0.1', host_port=8080, container_port=80,
                          prerender=False, capture_api=False,
                          checksums=False, verify_after=False, incremental=False, diff_latest=False,
                          plugins_dir=plugdir, json_logs=False, profile=False, open_browser=False,
                          run_built=False, serve_folder=False, estimate_first=False)
        setattr(cfg,'cleanup', False)
        res = clone_site(cfg, CB())
        assert res.success
        manifest_path = os.path.join(res.output_folder,'clone_manifest.json')
        data = json.load(open(manifest_path,'r',encoding='utf-8'))
        assert data.get('finalize_custom', {}).get('added') is True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
