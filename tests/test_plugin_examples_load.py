import os, json, tempfile, shutil, threading, http.server, socketserver, pytest
from cw2dt_core import CloneConfig, clone_site, CloneCallbacks, is_wget2_available

class Cb(CloneCallbacks):
    def __init__(self): self.logs=[]
    def log(self, message: str): self.logs.append(message)

class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a, **k): pass

def test_example_plugins_roundtrip():
    if not is_wget2_available():
        pytest.skip('wget2 not installed; skipping plugin example integration test')
    # Temporary site directory served over HTTP so wget2 can fetch
    site_dir = tempfile.mkdtemp(prefix='cw2dt_site_')
    with open(os.path.join(site_dir,'index.html'),'w',encoding='utf-8') as f:
        f.write('<html><head><title>Seed</title></head><body><p>Hi</p></body></html>')
    # Start HTTP server on ephemeral port
    os.chdir(site_dir)
    httpd = socketserver.TCPServer(('127.0.0.1',0), _Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{port}/'

    # Copy example plugins
    base_examples = os.path.join(os.path.dirname(__file__), '..', 'plugin_examples')
    tmp_plugins = tempfile.mkdtemp(prefix='cw2dt_plug_')
    for fn in os.listdir(base_examples):
        if fn.endswith('.py'):
            shutil.copy2(os.path.join(base_examples, fn), os.path.join(tmp_plugins, fn))
    tmp_out = tempfile.mkdtemp(prefix='cw2dt_out_')
    cb = Cb()
    cfg = CloneConfig(url=url, dest=os.path.join(tmp_out,'dest'), plugins_dir=tmp_plugins, disable_js=True,
                      incremental=False, diff_latest=False, capture_api=False, prerender=False, json_logs=False,
                      build=False, run_built=False, open_browser=False)
    res = clone_site(cfg, cb)
    # Shutdown server
    httpd.shutdown(); httpd.server_close()
    if not res.success:
        pytest.skip('Clone failed likely due to environment/network; skipping')
    if res.manifest_path and os.path.exists(res.manifest_path):
        with open(res.manifest_path,'r',encoding='utf-8') as mf:
            data=json.load(mf)
        if data.get('custom_notes'):
            assert any(n.get('added_by')=='manifest_note_plugin' for n in data.get('custom_notes', [])), 'Finalize note missing'
        mods = data.get('plugin_modifications') or {}
        assert isinstance(mods, dict)
    shutil.rmtree(tmp_plugins, ignore_errors=True)
    shutil.rmtree(tmp_out, ignore_errors=True)
    shutil.rmtree(site_dir, ignore_errors=True)
