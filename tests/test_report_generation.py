import os, json, tempfile, shutil, subprocess, sys
import pytest

CLI_BASE = [sys.executable, 'cw2dt.py', '--headless']
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

@pytest.mark.skipif(shutil.which('wget2') is None, reason='wget2 not installed')
def test_report_json_generation():
    tmp = tempfile.mkdtemp(prefix='cw2dt_rep_')
    try:
        # simple http server site directory
        site=os.path.join(tmp,'site')
        os.makedirs(site, exist_ok=True)
        with open(os.path.join(site,'index.html'),'w',encoding='utf-8') as f: f.write('<html><head><title>A</title></head><body>X</body></html>')
        # Start server
        import http.server, socketserver, threading
        os.chdir(site)
        httpd = socketserver.TCPServer(('127.0.0.1',0), http.server.SimpleHTTPRequestHandler)
        port=httpd.server_address[1]
        t=threading.Thread(target=httpd.serve_forever, daemon=True); t.start()
        url=f'http://127.0.0.1:{port}/'
        out_dir=os.path.join(tmp,'out')
        cmd=CLI_BASE + ['--url', url, '--dest', out_dir, '--docker-name','site','--report','json']
        res=subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
        httpd.shutdown(); httpd.server_close()
        report_path=os.path.join(out_dir,'site','clone_report.json')
        assert os.path.exists(report_path)
        data=json.loads(open(report_path,'r',encoding='utf-8').read())
        assert isinstance(data.get('exit_code'), int)
        assert data.get('url') == url
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

@pytest.mark.skipif(shutil.which('wget2') is None, reason='wget2 not installed')
def test_report_markdown_generation():
    tmp = tempfile.mkdtemp(prefix='cw2dt_rep_')
    try:
        site=os.path.join(tmp,'site')
        os.makedirs(site, exist_ok=True)
        with open(os.path.join(site,'index.html'),'w',encoding='utf-8') as f: f.write('<html><head><title>B</title></head><body>Y</body></html>')
        import http.server, socketserver, threading
        os.chdir(site)
        httpd = socketserver.TCPServer(('127.0.0.1',0), http.server.SimpleHTTPRequestHandler)
        port=httpd.server_address[1]
        t=threading.Thread(target=httpd.serve_forever, daemon=True); t.start()
        url=f'http://127.0.0.1:{port}/'
        out_dir=os.path.join(tmp,'out')
        cmd=CLI_BASE + ['--url', url, '--dest', out_dir, '--docker-name','site','--report','md']
        res=subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
        httpd.shutdown(); httpd.server_close()
        report_path=os.path.join(out_dir,'site','clone_report.md')
        assert os.path.exists(report_path)
        text=open(report_path,'r',encoding='utf-8').read()
        assert '# Clone Report' in text
        assert 'Overview' in text
        assert 'Exit Code' in text
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
