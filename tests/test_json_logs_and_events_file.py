import os, sys, tempfile, shutil, json

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site


class CB(cw2dt_core.CloneCallbacks):
    def __init__(self): self.lines=[]
    def log(self, message: str): self.lines.append(message)


def test_json_logs_and_events_file_envelope_order():
    tmp = tempfile.mkdtemp(prefix='cw2dt_events_')
    try:
        events_path = os.path.join(tmp,'events.ndjson')
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        def _wget_stub(cmd, cb):
            root = os.path.join(cfg.dest, cfg.docker_name)
            os.makedirs(root, exist_ok=True)
            open(os.path.join(root,'index.html'),'w').write('<html></html>')
            return True
        cw2dt_core._wget2_progress = _wget_stub  # type: ignore
        # Minimal prerender stub
        cw2dt_core._run_prerender = lambda **k: {'pages_processed':1,'routes_discovered':0,'api_captured':0}  # type: ignore
        cfg = CloneConfig(url='http://events.local', dest=tmp, docker_name='site', json_logs=True,
                          events_file=events_path, prerender=True)
        setattr(cfg,'cleanup', False)
        cb = CB()
        clone_site(cfg, cb)
        # Ensure some JSON log lines emitted
        json_lines = [l for l in cb.lines if l.startswith('{') and l.endswith('}')]
        assert json_lines, 'Expected JSON log lines'
        # Events file ordering & schema
        assert os.path.exists(events_path)
        with open(events_path,'r',encoding='utf-8') as f:
            rows = [json.loads(x) for x in f.read().strip().splitlines() if x.strip()]
        assert rows, 'No events written'
        # Sequence numbers strictly increasing
        seqs = [r['seq'] for r in rows]
        assert seqs == sorted(seqs)
        # Required envelope fields present
        for r in rows[:3]:
            for k in ('event','ts','seq','run_id','schema_version','tool_version'):
                assert k in r
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
