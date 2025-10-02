import os, sys, json, tempfile, shutil, subprocess

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

SCRIPT = os.path.join(BASE,'cw2dt.py')
PY = sys.executable

def run_cli(args):
    return subprocess.run([PY, SCRIPT, '--headless'] + args, capture_output=True, text=True)


def test_config_file_merge_for_prerender_and_router():
    tmp = tempfile.mkdtemp(prefix='cw2dt_cfgmerge_')
    try:
        cfg_path = os.path.join(tmp,'conf.json')
        json.dump({
            "prerender": True,
            "router_intercept": True,
            "capture_api": True,
            "prerender_max_pages": 12
        }, open(cfg_path,'w',encoding='utf-8'))
        # Provide only required base flags on CLI; others come from config
        r = run_cli(['--url','http://example.com','--dest',tmp,'--docker-name','cfg','--config',cfg_path,'--print-repro'])
        assert r.returncode == 0, r.stderr
        out = r.stdout.strip()
        # Should reflect merged config values
        assert '--prerender' in out and '--router-intercept' in out and '--capture-api' in out
        assert '--prerender-max-pages=12' in out or '--prerender-max-pages 12' in out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
