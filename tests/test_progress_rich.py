import os, sys, json, tempfile, shutil, subprocess, pytest
from cw2dt_core import headless_main

@pytest.mark.skipif('rich' not in sys.modules and subprocess.run([sys.executable,'-c','import importlib,sys;import importlib.util;print(importlib.util.find_spec("rich") is None)'],capture_output=True,text=True).stdout.strip()=='True', reason='rich not installed')
def test_rich_progress_mode_runs():
    tmp = tempfile.mkdtemp(prefix='cw2dt_rich_')
    try:
        # Use a tiny site via file:// so wget2 must be present; if wget2 missing other tests already skip.
        index_path = os.path.join(tmp,'index.html')
        with open(index_path,'w',encoding='utf-8') as f: f.write('<html><body>ok</body></html>')
        # Invoke headless_main with rich progress; expect successful exit or wget2 missing exit.
        args=[f'--url=file://{index_path}', f'--dest={tmp}', '--docker-name=site', '--headless', '--progress=rich']
        rc = headless_main(args)
        # Accept success or wget-missing code; rich mode should not crash.
        assert rc in (0, 12), f'Unexpected exit code {rc}'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
