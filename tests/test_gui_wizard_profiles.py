import os, json, tempfile, pytest, importlib, importlib.util

spec = importlib.util.find_spec('PySide6')
if spec is None:
    pytest.skip('PySide6 not installed', allow_module_level=True)

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QEventLoop, QTimer

import cw2dt_gui
from cw2dt_gui import DockerClonerGUI

@pytest.fixture(scope='module')
def app():
    app = QApplication.instance() or QApplication([])
    yield app

@pytest.fixture
def gui(app):
    w = DockerClonerGUI()
    yield w
    w.close()

# Utility to process events

def process_events(ms=40):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()

def test_profile_save_and_load_roundtrip(gui, monkeypatch):
    # Set some fields
    gui.url_in.setText('https://example.com')
    gui.dest_in.setText('/tmp')
    gui.chk_prerender.setChecked(True)
    gui.chk_router.setChecked(True)
    gui.chk_checksums.setChecked(True)
    # Monkeypatch profile directory to a temp path
    tmpd = tempfile.mkdtemp()
    monkeypatch.setattr(DockerClonerGUI, '_profiles_dir', lambda self: tmpd)
    # Save
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: None)
    # Provide name automatically by patching QInputDialog
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, 'getText', lambda *a, **k: ('testprof', True))
    gui._save_profile_dialog()
    prof_path = os.path.join(tmpd, 'testprof.json')
    assert os.path.exists(prof_path)
    # Change values then load
    gui.chk_prerender.setChecked(False)
    gui.chk_router.setChecked(False)
    gui.chk_checksums.setChecked(False)
    from PySide6.QtWidgets import QInputDialog as _QID
    monkeypatch.setattr(_QID, 'getItem', lambda *a, **k: ('testprof.json', True))
    gui._load_profile_dialog()
    assert gui.chk_prerender.isChecked() is True
    assert gui.chk_router.isChecked() is True
    assert gui.chk_checksums.isChecked() is True

def test_wizard_applies_recommendations(gui, monkeypatch):
    # Monkeypatch network fetch to controlled content indicating a React SPA with many scripts
    sample_html = '<html><head><script></script>' + ('<script></script>'*20) + '<div data-reactroot></div></head><body></body></html>'
    import urllib.request
    class FakeResp:
        def __init__(self, data): self._d=data.encode(); self.headers={}
        def read(self, n): return self._d
        def __enter__(self): return self
        def __exit__(self,*a): pass
    monkeypatch.setattr(urllib.request, 'urlopen', lambda req, timeout=6.0: FakeResp(sample_html))
    gui.url_in.setText('https://example.com')
    # Suppress dialog interaction by auto-accepting
    # In offscreen mode _run_wizard will call _wizard_show_results directly; patch the result dialog
    from PySide6.QtWidgets import QDialogButtonBox, QDialog
    def patched_show_results(info):
        # Directly invoke apply helper with recommended values
        rec=info.get('recommend',{})
        gui._apply_wizard_recommendations(info, {
            'prerender': rec.get('prerender', True),
            'router_intercept': rec.get('router_intercept', True),
            'js_strip': False,
            'checksums': True,
            'incremental': True
        })
    monkeypatch.setattr(gui, '_wizard_show_results', patched_show_results)
    gui._run_wizard()
    # Expectations: prerender + router intercept enabled
    assert gui.chk_prerender.isChecked() is True
    assert gui.chk_router.isChecked() is True

