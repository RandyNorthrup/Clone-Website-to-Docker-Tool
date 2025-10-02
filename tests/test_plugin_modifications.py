import os, sys, tempfile, shutil, json, textwrap

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site

class CB(cw2dt_core.CloneCallbacks):
    def log(self, message: str): pass


def test_plugin_modification_counts():
    tmp = tempfile.mkdtemp(prefix='cw2dt_plug_')
    try:
        # Create plugin directory with a plugin that replaces token TEXT with MOD
        plugdir = os.path.join(tmp, 'plugins'); os.makedirs(plugdir, exist_ok=True)
        plugin_code = textwrap.dedent('''\
            def post_asset(rel, data, context):
                if rel.endswith('.html') and b'TEXT' in data:
                    return data.replace(b'TEXT', b'MOD')
            def finalize(output_folder, manifest, context):
                pass
        ''')
        open(os.path.join(plugdir,'mplug.py'),'w',encoding='utf-8').write(plugin_code)
        # Monkeypatch clone to avoid network
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        def _wget_stub(cmd, cb):
            root = os.path.join(cfg.dest, cfg.docker_name)
            os.makedirs(root, exist_ok=True)
            open(os.path.join(root,'index.html'),'wb').write(b'<html>TEXT</html>')
            open(os.path.join(root,'about.html'),'wb').write(b'<html>TEXT</html>')
            if cb:
                if callable(cb):
                    cb('clone',100)
                elif hasattr(cb,'progress'):
                    cb.progress('clone',100)
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
        # Check manifest plugin_modifications field
        mpath = os.path.join(res.output_folder,'clone_manifest.json')
        data = json.load(open(mpath,'r',encoding='utf-8'))
        mods = data.get('plugin_modifications') or {}
        # Expect mplug modified both html files
        assert mods.get('mplug') == 2, mods
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
