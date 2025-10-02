import os, sys, tempfile, shutil, json, textwrap

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site


class CB(cw2dt_core.CloneCallbacks):
    def log(self, message: str): pass


def test_plugin_errors_do_not_abort_clone():
    tmp = tempfile.mkdtemp(prefix='cw2dt_plugin_err_')
    try:
        plugdir=os.path.join(tmp,'plugins'); os.makedirs(plugdir, exist_ok=True)
        plugin_code=textwrap.dedent('''\
            def pre_download(ctx):
                raise RuntimeError('pre fail')
            def post_asset(asset, data, ctx):
                raise ValueError('post fail')
            def finalize(output_folder, manifest, ctx):
                raise Exception('finalize fail')
        ''')
        open(os.path.join(plugdir,'bad_plugin.py'),'w').write(plugin_code)
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        def _wget_stub(cmd, cb):
            root = os.path.join(cfg.dest, cfg.docker_name)
            os.makedirs(root, exist_ok=True)
            open(os.path.join(root,'index.html'),'w').write('<html></html>')
            return True
        cw2dt_core._wget2_progress=_wget_stub  # type: ignore
        cfg = CloneConfig(url='http://pluginerr.local', dest=tmp, docker_name='site', plugins_dir=plugdir)
        setattr(cfg,'cleanup', False)
        res = clone_site(cfg, CB())
        assert res.success, 'Clone should succeed despite plugin errors'
        data=json.load(open(os.path.join(res.output_folder,'clone_manifest.json'),'r',encoding='utf-8'))
        assert data.get('clone_success') is True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
