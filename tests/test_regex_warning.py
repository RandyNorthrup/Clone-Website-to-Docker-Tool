import os, tempfile, shutil, threading, http.server, socketserver, pytest
from cw2dt_core import CloneConfig, clone_site, CloneCallbacks, is_wget2_available

class Cb(CloneCallbacks):
    def __init__(self): self.lines=[]
    def log(self, message: str): self.lines.append(message)

def test_regex_warning_emitted_for_risky_patterns():
    if not is_wget2_available():
        pytest.skip('wget2 not installed')
    tmp = tempfile.mkdtemp(prefix='cw2dt_regex_')
    try:
        site=os.path.join(tmp,'site'); os.makedirs(site, exist_ok=True)
        with open(os.path.join(site,'index.html'),'w',encoding='utf-8') as f:
            f.write('<html><head><title>R</title></head><body>X</body></html>')
        os.chdir(site)
        httpd = socketserver.TCPServer(('127.0.0.1',0), http.server.SimpleHTTPRequestHandler)
        port=httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        url=f'http://127.0.0.1:{port}/'
        cb = Cb()
        cfg = CloneConfig(url=url, dest=os.path.join(tmp,'out'), disable_js=True, router_intercept=True,
                          router_allow=['(.*.*foo)', '(a+b+)+'], json_logs=True)
        clone_site(cfg, cb)
        httpd.shutdown(); httpd.server_close()
        warnings=[l for l in cb.lines if 'regex_warning' in l]
        assert warnings, 'Expected regex_warning events'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
