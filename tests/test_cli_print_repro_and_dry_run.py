import os, sys, json, tempfile, shutil, subprocess, textwrap

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import cw2dt_core  # ensure importable

PY_EXEC = sys.executable

SCRIPT = os.path.join(BASE,'cw2dt.py') if os.path.exists(os.path.join(BASE,'cw2dt.py')) else os.path.join(BASE,'cw2dt_core.py')

def run_cli(args: list[str]):
    cmd=[PY_EXEC, SCRIPT, '--headless'] + args
    return subprocess.run(cmd,capture_output=True,text=True)

def test_print_repro_outputs_command():
    tmp = tempfile.mkdtemp(prefix='cw2dt_cli_')
    try:
        r=run_cli(['--url','http://example.com','--dest',tmp,'--docker-name','t','--print-repro','--prerender','--capture-api','--checksums'])
        assert r.returncode==0, r.stderr
        out=r.stdout.strip()
        assert 'cw2dt.py' in out and '--prerender' in out and '--capture-api' in out and '--checksums' in out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def test_dry_run_json_logs():
    tmp = tempfile.mkdtemp(prefix='cw2dt_cli_')
    try:
        r=run_cli(['--url','http://example.com','--dest',tmp,'--docker-name','t','--dry-run','--json-logs'])
        assert r.returncode in (0,12)
        data=json.loads(r.stdout)
        assert 'dry_run_plan' in data
        plan=data['dry_run_plan']
        assert plan['url']=='http://example.com'
        assert plan['will_prerender'] is False
        assert plan['dest']==tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
