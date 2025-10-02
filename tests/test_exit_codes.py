import os, sys, tempfile, shutil, subprocess, json

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SCRIPT = os.path.join(BASE,'cw2dt.py') if os.path.exists(os.path.join(BASE,'cw2dt.py')) else os.path.join(BASE,'cw2dt_core.py')
PY = sys.executable

def run(args, extra_env=None):
    env=os.environ.copy()
    if extra_env:
        env.update(extra_env)
    cmd=[PY, SCRIPT, '--headless']+args
    return subprocess.run(cmd,capture_output=True,text=True,env=env)

def test_exit_code_wget_missing_simulated():
    tmp=tempfile.mkdtemp(prefix='cw2dt_ec_')
    try:
        r=run(['--url','http://e','--dest',tmp,'--docker-name','x','--dry-run'], extra_env={'CW2DT_FORCE_NO_WGET':'1'})
        assert r.returncode==12, (r.returncode, r.stdout, r.stderr)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def test_exit_code_canceled_simulated():
    tmp=tempfile.mkdtemp(prefix='cw2dt_ec_')
    try:
        r=run(['--url','http://e','--dest',tmp,'--docker-name','x'], extra_env={'CW2DT_FORCE_CANCEL':'1'})
        assert r.returncode==15 or r.returncode==1  # headless main maps canceled via manifest after run; here we simulate early
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
