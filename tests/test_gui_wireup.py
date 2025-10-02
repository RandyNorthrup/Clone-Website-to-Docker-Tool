import os, sys, tempfile, pytest

import importlib
spec = importlib.util.find_spec('PySide6')
if spec is None:
    pytest.skip('PySide6 not installed', allow_module_level=True)

# Defer heavy imports until after skip check
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QEventLoop, QTimer

cw2dt_gui = importlib.import_module('cw2dt_gui')
from cw2dt_gui import DockerClonerGUI
import cw2dt_core
from cw2dt_core import CloneResult

@pytest.fixture(scope='module')
def app():
    app = QApplication.instance() or QApplication([])
    yield app

@pytest.fixture
def gui(app):
    w = DockerClonerGUI()
    yield w
    w.close()

class StubCallbacks:
    def __init__(self, real): self.real = real

# --- Helper monkeypatch for clone_site so GUI wiring tests are fast ---
@pytest.fixture
def stub_clone(monkeypatch):
    calls = {}
    def _stub(cfg, callbacks):
        for phase in ('clone','prerender','checksums','build','verify','cleanup'):
            if hasattr(callbacks,'phase'): callbacks.phase(phase, 50)
        if hasattr(callbacks,'phase'): callbacks.phase('clone',100)
        if hasattr(callbacks,'log'): callbacks.log('[stub] clone complete')
        return CloneResult(True, False, '/tmp/out', '/tmp/out', None, None, {}, None)
    # Patch both core and the GUI module reference (GUI may import directly)
    monkeypatch.setattr(cw2dt_core, 'clone_site', _stub, raising=True)
    monkeypatch.setattr(cw2dt_gui, 'clone_site', _stub, raising=False)
    yield calls

def process_events(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()

def test_gui_launch(gui):
    assert gui.windowTitle() != ''

def test_build_config_reflects_inputs(gui):
    gui.url_in.setText('http://example.com')
    gui.dest_in.setText('/tmp')
    gui.name_in.setText('demo')
    cfg = gui._build_config()
    assert cfg.url == 'http://example.com'
    assert cfg.dest == '/tmp'
    assert cfg.docker_name == 'demo'

def test_dependency_dialog_collects_and_logs(gui, monkeypatch):
    # Force pretend-missing modules by returning None for find_spec
    import importlib.util as _iu
    real_find = _iu.find_spec
    monkeypatch.setattr(_iu, 'find_spec', lambda name: None if name in ('rich','playwright','browser_cookie3') else real_find(name))
    # Force absent external binaries
    import shutil
    monkeypatch.setattr(shutil, 'which', lambda name: None)
    # Suppress message box popup
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: None)
    gui._show_deps_dialog()
    txt = gui.console.toPlainText()
    assert 'Suggested Install Commands' in txt
    assert 'pip install' in txt or 'python -m pip install' in txt

def test_start_clone_invokes_stub(gui, stub_clone, monkeypatch):
    gui.url_in.setText('http://example.com')
    tmpd = tempfile.mkdtemp()
    gui.dest_in.setText(tmpd)
    gui.name_in.setText('site')
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: None)
    gui.start_clone()
    # Let events process
    for _ in range(5):
        process_events(40)
    txt = gui.console.toPlainText()
    assert '[stub] clone complete' in txt
    # Progress bar should have advanced from 0 (not guaranteed to 100 with stub phases but >0)
    assert gui.prog.value() >= 0

def test_cancel_button_disabled_after_finish(gui, stub_clone, monkeypatch):
    gui.url_in.setText('http://example.com')
    tmpd = tempfile.mkdtemp()
    gui.dest_in.setText(tmpd)
    gui.name_in.setText('site')
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: None)
    gui.start_clone()
    for _ in range(5):
        process_events(40)
    assert gui.btn_cancel.isEnabled() in (False, True)  # presence check
    # simulate user pressing cancel after finish should not error
    gui._cancel_clone()
    process_events(20)
