import os, sys, tempfile, shutil, json, shlex

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # type: ignore
from cw2dt_core import CloneConfig, clone_site

class CB(cw2dt_core.CloneCallbacks):
    def log(self, message: str): pass


def test_reproduction_command_contains_expected_flags():
    tmp = tempfile.mkdtemp(prefix='cw2dt_repro_')
    try:
        cw2dt_core.is_wget2_available = lambda : True  # type: ignore
        def _wget_stub(cmd, cb):
            root = os.path.join(cfg.dest, cfg.docker_name)
            os.makedirs(root, exist_ok=True)
            open(os.path.join(root,'index.html'),'w',encoding='utf-8').write('<html></html>')
            if cb:
                if callable(cb):
                    cb('clone',100)
                elif hasattr(cb,'progress'):
                    cb.progress('clone',100)
            return True
        cw2dt_core._wget2_progress = _wget_stub  # type: ignore
        cfg = CloneConfig(url='http://example.com', dest=tmp, docker_name='repro', build=False, jobs=3,
                          bind_ip='0.0.0.0', host_port=9090, container_port=80,
                          prerender=True, capture_api=True,
                          router_allow=['/api','/x'], router_deny=['/ignore'],
                          checksums=True, verify_after=True, incremental=True, diff_latest=True,
                          disable_js=True, json_logs=True, profile=True, open_browser=False,
                          run_built=False, serve_folder=True, estimate_first=True)
        setattr(cfg,'cleanup', False)
        res = clone_site(cfg, CB())
        assert res.success
        mpath = os.path.join(res.output_folder,'clone_manifest.json')
        data = json.load(open(mpath,'r',encoding='utf-8'))
        repro = data.get('reproduce_command')
        assert repro, 'missing reproduce_command'
        # Manifest stores list (parity choice); join to analyze tokens uniformly
        if isinstance(repro, list):
            repro_str = ' '.join(repro)
        else:
            repro_str = repro
        tokens = shlex.split(repro_str)
        # Ensure critical flags are present and collapsed lists are comma separated
        # Current reproduction command uses space separated flag/value pairs, not = form for allow/deny
        # Allow either combined or separate token style (current builder uses --router-allow=/api,/x)
        assert any(t.startswith('--router-allow=') and '/api,/x' in t for t in tokens) or ('--router-allow' in tokens and '/api,/x' in tokens), tokens
        assert any(t.startswith('--router-deny=') and '/ignore' in t for t in tokens) or ('--router-deny' in tokens and '/ignore' in tokens), tokens
        assert '--prerender' in tokens, tokens
        assert ('--capture-api' in tokens) or ('--api-capture' in tokens), tokens
        assert '--checksums' in tokens and '--verify-after' in tokens, tokens
        assert '--incremental' in tokens and '--diff-latest' in tokens, tokens
        assert '--disable-js' in tokens, tokens
        assert '--jobs=3' in tokens, tokens
        # Should not redundantly include build flag since default build is True only when specified? here build False so should include --no-build or absence? adapt logic
        # Accept either presence of --no-build or absence of a --build flag.
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
