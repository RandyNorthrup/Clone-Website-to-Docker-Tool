import os, sys, tempfile, shutil, types

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site


class CB(cw2dt_core.CloneCallbacks):
    def log(self, message: str):
        pass


def _install_fake_playwright(html='<html><body>stub</body></html>'):
    # Build fake playwright.sync_api with minimal surface used in _run_prerender
    if 'playwright' in sys.modules:
        del sys.modules['playwright']
    if 'playwright.sync_api' in sys.modules:
        del sys.modules['playwright.sync_api']
    pw_pkg = types.ModuleType('playwright')
    sync_api = types.ModuleType('playwright.sync_api')

    class FakePage:
        def __init__(self): self._closed=False
        def goto(self, url, wait_until=None): return None
        def add_init_script(self, script): pass
        def wait_for_timeout(self, ms): pass
        def wait_for_selector(self, sel, timeout=None): pass
        def evaluate(self, script):
            # Return a plausible value when dom stable polling queries timestamp
            if 'Date.now() - (window.__cw2dt_last_mut' in script:
                return 999999
            return None
        def query_selector_all(self, q): return []
        def content(self): return html
        def expose_binding(self, *a, **k): pass
        def close(self): self._closed=True

    class FakeContext:
        def __init__(self): self._responses=[]
        def new_page(self): return FakePage()
        def on(self, evt, cb): pass

    class FakeBrowser:
        def new_context(self): return FakeContext()
        def close(self): pass

    class PWManager:
        def __enter__(self):
            class Chromium:
                def launch(self, headless=True): return FakeBrowser()
            return types.SimpleNamespace(chromium=Chromium())
        def __exit__(self, exc_type, exc, tb): return False

    def sync_playwright():
        return PWManager()

    sync_api.sync_playwright = sync_playwright  # type: ignore
    sys.modules['playwright'] = pw_pkg
    sys.modules['playwright.sync_api'] = sync_api


def test_hook_script_invoked_with_fake_playwright():
    tmp = tempfile.mkdtemp(prefix='cw2dt_hook_')
    prev_env = os.environ.get('CW2DT_FORCE_NO_PLAYWRIGHT')
    try:
        # Force-disable playwright to exercise early-return path which now invokes hook
        os.environ['CW2DT_FORCE_NO_PLAYWRIGHT'] = '1'
        # Ensure wget2 path is stubbed
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        def _wget_stub(cmd, cb):
            root = os.path.join(cfg.dest, cfg.docker_name)
            os.makedirs(root, exist_ok=True)
            open(os.path.join(root,'index.html'),'w').write('<html></html>')
            return True
        cw2dt_core._wget2_progress = _wget_stub  # type: ignore
        # (Optional) install fake playwright; not required when force-disabled but harmless
        _install_fake_playwright()
        # Create hook script that writes a marker file
        hook_path = os.path.join(tmp,'hook.py')
        marker = os.path.join(tmp,'hook_ran.txt')
        open(hook_path,'w',encoding='utf-8').write(
            'def on_page(page,url,context):\n'
            '    open(r"'+marker+'","w").write("ok")\n'
        )
        cfg = CloneConfig(url='http://example.local', dest=tmp, docker_name='site',
                          prerender=True, hook_script=hook_path, prerender_max_pages=1)
        setattr(cfg,'cleanup', False)
        res = clone_site(cfg, CB())
        assert res.success
        assert os.path.exists(marker), 'Hook on_page not invoked'
    finally:
        if prev_env is not None:
            os.environ['CW2DT_FORCE_NO_PLAYWRIGHT'] = prev_env
        else:
            os.environ.pop('CW2DT_FORCE_NO_PLAYWRIGHT', None)
        shutil.rmtree(tmp, ignore_errors=True)
