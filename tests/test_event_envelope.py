import json, os, shutil, tempfile
from cw2dt_core import CloneConfig, clone_site, CloneCallbacks

class _Cb(CloneCallbacks):
    def __init__(self):
        self.lines=[]
    def log(self, message: str):
        self.lines.append(message)

def test_event_envelope_structure():
    tmp = tempfile.mkdtemp(prefix='cw2dt_evt_')
    try:
        site_dir = os.path.join(tmp, 'seed')
        os.makedirs(site_dir, exist_ok=True)
        index_path = os.path.join(site_dir, 'index.html')
        with open(index_path, 'w', encoding='utf-8') as f:
            f.write('<html><head><title>Test</title></head><body>Hello</body></html>')
        url = 'file://' + index_path
        cb = _Cb()
        events_file = os.path.join(tmp,'events.ndjson')
        cfg = CloneConfig(url=url, dest=os.path.join(tmp,'out'), docker_name='site', build=False,
                          incremental=False, diff_latest=False, capture_api=False, prerender=False,
                          router_intercept=False, run_built=False, disable_js=True, plugins_dir=None, json_logs=True,
                          profile=False, open_browser=False, serve_folder=False, estimate_first=False, cleanup=False,
                          events_file=events_file)
        clone_site(cfg, cb)
        json_lines = []
        for line in cb.lines:
            s=line.strip()
            if not s.startswith('{'):
                continue
            try:
                obj=json.loads(s)
            except Exception:
                continue
            if 'event' in obj:
                json_lines.append(obj)
        assert json_lines, 'No JSON events captured'
        run_ids = {o.get('run_id') for o in json_lines if 'run_id' in o}
        assert len(run_ids)==1, 'run_id should be constant'
        seqs = [o.get('seq') for o in json_lines if isinstance(o.get('seq'), int)]
        assert seqs == sorted(seqs), 'seq must be monotonically increasing'
        assert seqs[0] == 1, 'seq should start at 1'
        start = json_lines[0]
        assert start['event']=='start'
        for key in ['ts','run_id','schema_version','seq']:
            assert key in start
        summary = json_lines[-1]
        assert summary['event']=='summary'
        assert 'success' in summary
        # exit_code may appear only when run via headless_main; ensure absence doesn't fail test
        # events file should also contain lines
        if os.path.exists(events_file):
            lines=open(events_file,'r',encoding='utf-8').read().strip().splitlines()
            assert lines, 'events file empty'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
# (No change required for direct clone_site test; a separate CLI test would cover summary_final.)
