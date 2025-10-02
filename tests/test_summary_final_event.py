import os, tempfile, subprocess, sys, json, shutil, pytest

@pytest.mark.skipif(shutil.which('wget2') is None, reason='wget2 not installed')
def test_summary_final_event_contains_exit_code():
    tmp = tempfile.mkdtemp(prefix='cw2dt_sum_')
    try:
        # Minimal site served
        site=os.path.join(tmp,'site')
        os.makedirs(site, exist_ok=True)
        with open(os.path.join(site,'index.html'),'w',encoding='utf-8') as f:
            f.write('<html><head><title>Z</title></head><body>Q</body></html>')
        import http.server, socketserver, threading
        os.chdir(site)
        httpd = socketserver.TCPServer(('127.0.0.1',0), http.server.SimpleHTTPRequestHandler)
        port=httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        url=f'http://127.0.0.1:{port}/'
        out_dir=os.path.join(tmp,'out')
        events_path=os.path.join(tmp,'events.ndjson')
        cmd=[sys.executable,'cw2dt.py','--headless','--json-logs','--events-file',events_path,'--url',url,'--dest',out_dir,'--docker-name','site']
        res=subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.abspath(os.path.join(os.path.dirname(__file__),'..')))
        httpd.shutdown(); httpd.server_close()
        # Parse stdout JSON lines
        lines=[l for l in res.stdout.splitlines() if l.strip().startswith('{')]
        parsed=[json.loads(l) for l in lines if 'summary' in l or 'summary_final' in l]
        assert any(o.get('event')=='summary_final' and 'exit_code' in o for o in parsed), 'summary_final with exit_code missing'
        if os.path.exists(events_path):
            elines=[json.loads(l) for l in open(events_path,'r',encoding='utf-8').read().splitlines() if l.strip()]
            assert any(o.get('event')=='summary_final' for o in elines), 'events file missing summary_final'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
