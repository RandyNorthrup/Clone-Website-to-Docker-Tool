"""Qt GUI frontend for Clone Website to Docker Tool with modular pipeline.

Adds weighted multi-phase progress, cooperative cancellation, estimate-first option,
MRU dropdown history, and phase timing summary.
"""
from __future__ import annotations

import os, sys, json, webbrowser, time, re
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QTextEdit, QCheckBox, QSpinBox, QMessageBox, QProgressBar, QGroupBox, QComboBox, QSplitter,
    QScrollArea, QToolButton, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, QThread, Signal, QEvent, QSize
from PySide6.QtGui import QPixmap, QIcon

from cw2dt_core import (
    validate_required_fields, is_wget2_available, docker_available,
    port_in_use, CloneConfig, clone_site, CloneCallbacks
)

class _GuiCallbacks(CloneCallbacks):
    def __init__(self, owner: 'DockerClonerGUI'): self._owner=owner
    def _pause_gate(self):
        # If paused, spin until resumed or canceled
        from PySide6.QtCore import QCoreApplication
        while getattr(self._owner,'_paused',False) and not self.is_canceled():
            QCoreApplication.processEvents()
            time.sleep(0.05)
    def log(self, message: str): self._pause_gate(); self._owner.sig_log.emit(message)
    def phase(self, phase: str, pct: int): self._pause_gate(); self._owner.sig_phase.emit(phase, pct)
    def bandwidth(self, rate: str): self._pause_gate(); self._owner.sig_bandwidth.emit(rate)
    def api_capture(self, count: int): self._pause_gate(); self._owner.sig_api.emit(count)
    def router_count(self, count: int): self._pause_gate(); self._owner.sig_router.emit(count)
    def checksum(self, pct: int): self._pause_gate(); self._owner.sig_checksum.emit(pct)
    def is_canceled(self)->bool:
        w=self._owner.worker
        return bool(getattr(w,'_cancel',False)) if w else False

class _CloneWorker(QThread):
    finished = Signal(object)
    def __init__(self,cfg:CloneConfig,cb:_GuiCallbacks):
        super().__init__(); self.cfg=cfg; self.cb=cb; self._cancel=False
    def cancel(self): self._cancel=True
    def run(self):
        res=clone_site(self.cfg,self.cb); self.finished.emit(res)

class _CollapsibleBox(QWidget):
    """Collapsible section with header spanning width."""
    def __init__(self, title: str):
        super().__init__()
        self._toggle = QToolButton(); self._toggle.setText(title); self._toggle.setCheckable(True); self._toggle.setChecked(False)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setArrowType(Qt.ArrowType.RightArrow)
        self._toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._toggle.clicked.connect(self._on_toggled)
        self._content = QWidget(); self._content.setVisible(False)
        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(1)
        header=QHBoxLayout(); header.setContentsMargins(0,0,0,0); header.addWidget(self._toggle); lay.addLayout(header)
        lay.addWidget(self._content)
        self._content_lay = QVBoxLayout(self._content); self._content_lay.setContentsMargins(10,4,10,8); self._content_lay.setSpacing(4)
        sep=QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setFrameShadow(QFrame.Shadow.Sunken); lay.addWidget(sep)
    def addWidget(self,w): self._content_lay.addWidget(w)
    def addLayout(self,l): self._content_lay.addLayout(l)
    def _on_toggled(self):
        o=self._toggle.isChecked(); self._toggle.setArrowType(Qt.ArrowType.DownArrow if o else Qt.ArrowType.RightArrow); self._content.setVisible(o)

class DockerClonerGUI(QWidget):
    sig_log=Signal(str); sig_phase=Signal(str,int); sig_bandwidth=Signal(str); sig_api=Signal(int); sig_router=Signal(int); sig_checksum=Signal(int)
    def __init__(self):
        super().__init__(); self.setWindowTitle('Clone Website to Docker Tool')
        self.worker=None; self._paused=False; self._last_result=None; self._serve_httpd=None; self._serve_thread=None
        # Track geometry to enforce right-edge-only horizontal resizing
        self._anchor_left=None
        self._last_size=None
        self._build_ui(); self._connect_signals(); self._update_dependency_banner()
        self._weighted={}; self._phase_pct={}; self._phase_start={}; self._phase_end={}

    def _add_banner_images(self, layout: QHBoxLayout):
        """Center three specific logos (web_logo.png, arrow_right.png, docker_logo.png) and set app icon icon.png."""
        try:
            base=os.path.join(os.path.dirname(__file__),'images')
            # Set window icon from icon.png if present
            ic_png=os.path.join(base,'icon.png')
            if os.path.exists(ic_png):
                self.setWindowIcon(QIcon(ic_png))
            else:
                # fallback chain: root icon.icns, root icon.ico, root icon.png
                root_dir=os.path.dirname(__file__)
                for ic in ('icon.icns','icon.ico','icon.png'):
                    ip=os.path.join(root_dir,ic)
                    if os.path.exists(ip):
                        self.setWindowIcon(QIcon(ip)); break
            logos=['web_logo.png','arrow_right.png','docker_logo.png']
            layout.addStretch(1)
            for name in logos:
                path=os.path.join(base,name)
                if os.path.exists(path):
                    pm=QPixmap(path)
                    if not pm.isNull():
                        lbl=QLabel(); lbl.setPixmap(pm.scaledToHeight(56, Qt.TransformationMode.SmoothTransformation)); layout.addWidget(lbl)
            layout.addStretch(1)
        except Exception:
            pass

    def _build_ui(self):
        root=QVBoxLayout(self); root.setContentsMargins(4,4,4,4)
        banner=QHBoxLayout(); banner.setSpacing(8); self._add_banner_images(banner); root.addLayout(banner)
        class _NoDragSplitter(QSplitter):
            def createHandle(self):
                h=super().createHandle(); h.installEventFilter(self); return h
            def eventFilter(self,obj,ev):
                if ev.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove):
                    return True
                return QSplitter.eventFilter(self,obj,ev)
        self.splitter=_NoDragSplitter(Qt.Orientation.Horizontal); self.splitter.setChildrenCollapsible(False); self.splitter.setHandleWidth(0); self.splitter.setStyleSheet("QSplitter::handle{background:transparent; width:0px;}"); root.addWidget(self.splitter,1)
        # Left scrollable config
        config_container=QWidget(); config_v=QVBoxLayout(config_container); config_v.setContentsMargins(4,4,4,4); config_v.setSpacing(6)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(config_container); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded); self.splitter.addWidget(scroll)
        self._config_container=config_container; self._config_scroll=scroll
        # Basic
        self._sections=[]
        basic=_CollapsibleBox('Basic Settings'); self._sections.append(basic); form=QGridLayout(); form.setContentsMargins(0,0,0,0); r=0
        form.addWidget(QLabel('Website URL:'),r,0); self.url_in=QLineEdit(); form.addWidget(self.url_in,r,1,1,2); r+=1
        form.addWidget(QLabel('Destination Folder:'),r,0); self.dest_in=QLineEdit(); form.addWidget(self.dest_in,r,1); b=QPushButton('Browse'); form.addWidget(b,r,2); b.clicked.connect(self._browse_dest); r+=1
        form.addWidget(QLabel('Docker Name:'),r,0); self.name_in=QLineEdit('site'); form.addWidget(self.name_in,r,1,1,2); r+=1
        form.addWidget(QLabel('Bind IP:'),r,0); self.ip_in=QLineEdit('127.0.0.1'); form.addWidget(self.ip_in,r,1)
        form.addWidget(QLabel('Host Port:'),r,2); self.host_port=QSpinBox(); self.host_port.setRange(1,65535); self.host_port.setValue(8080); form.addWidget(self.host_port,r,3); r+=1
        form.addWidget(QLabel('Container Port:'),r,0); self.cont_port=QSpinBox(); self.cont_port.setRange(1,65535); self.cont_port.setValue(80); form.addWidget(self.cont_port,r,1)
        basic.addLayout(form); config_v.addWidget(basic)
        # Clone options
        clone=_CollapsibleBox('Clone Options'); self._sections.append(clone); self.chk_build=QCheckBox('Build Docker image'); self.chk_run_built=QCheckBox('Run built image'); self.chk_serve=QCheckBox('Serve folder via nginx:alpine'); self.chk_open_browser=QCheckBox('Open browser after start'); self.chk_incremental=QCheckBox('Incremental (-N)'); self.chk_diff=QCheckBox('Diff vs last state'); self.chk_estimate_first=QCheckBox('Estimate before clone'); self.chk_cleanup=QCheckBox('Cleanup build artifacts')
        for w in (self.chk_build,self.chk_run_built,self.chk_serve,self.chk_open_browser,self.chk_incremental,self.chk_diff,self.chk_estimate_first,self.chk_cleanup): clone.addWidget(w)
        config_v.addWidget(clone)
        # Dynamic
        dyn=_CollapsibleBox('Dynamic / Prerender'); self._sections.append(dyn); self.chk_prerender=QCheckBox('Prerender (Playwright)'); self.spin_prer_pages=QSpinBox(); self.spin_prer_pages.setRange(1,2000); self.spin_prer_pages.setValue(40); self.chk_capture_api=QCheckBox('Capture API JSON'); self.hook_in=QLineEdit(); hr=QHBoxLayout(); hr.addWidget(QLabel('Hook Script:')); hr.addWidget(self.hook_in); hb=QPushButton('...'); hr.addWidget(hb); hb.clicked.connect(lambda: self._pick_file(self.hook_in)); dyn.addWidget(self.chk_prerender); dyn.addWidget(QLabel('Max Pages:')); dyn.addWidget(self.spin_prer_pages); dyn.addWidget(self.chk_capture_api); dyn.addLayout(hr); config_v.addWidget(dyn)
        # Router
        router=_CollapsibleBox('Router Interception'); self._sections.append(router); self.chk_router=QCheckBox('Enable Router Intercept'); self.chk_route_hash=QCheckBox('Include hash fragment (#)'); self.chk_router_quiet=QCheckBox('Quiet route logs'); self.spin_router_max=QSpinBox(); self.spin_router_max.setRange(1,10000); self.spin_router_max.setValue(200); self.spin_router_settle=QSpinBox(); self.spin_router_settle.setRange(0,10000); self.spin_router_settle.setValue(350); self.router_wait_sel=QLineEdit(); self.router_allow=QLineEdit(); self.router_deny=QLineEdit();
        for w in (self.chk_router,self.chk_route_hash,self.chk_router_quiet): router.addWidget(w)
        for pair in ((QLabel('Max Routes:'),self.spin_router_max),(QLabel('Settle ms:'),self.spin_router_settle),(QLabel('Wait Selector:'),self.router_wait_sel),(QLabel('Allow (regex,comma):'),self.router_allow),(QLabel('Deny (regex,comma):'),self.router_deny)):
            router.addWidget(pair[0]); router.addWidget(pair[1])
        config_v.addWidget(router)
        # Integrity
        integ=_CollapsibleBox('Integrity & Verification'); self._sections.append(integ); self.chk_checksums=QCheckBox('Compute Checksums'); self.chk_verify_after=QCheckBox('Verify after clone'); self.chk_verify_deep=QCheckBox('Deep verify'); self.checksum_ext=QLineEdit(); self.checksum_ext.setPlaceholderText('extra ext: css,js,png')
        for w in (self.chk_checksums,self.chk_verify_after,self.chk_verify_deep,self.checksum_ext): integ.addWidget(w)
        config_v.addWidget(integ)
        # Misc
        misc=_CollapsibleBox('Misc & Performance'); self._sections.append(misc); self.chk_disable_js=QCheckBox('Disable JS (strip <script>)'); self.size_cap=QLineEdit(); self.size_cap.setPlaceholderText('Size cap e.g. 500M'); self.throttle=QLineEdit(); self.throttle.setPlaceholderText('Throttle e.g. 2M'); self.auth_user=QLineEdit(); self.auth_user.setPlaceholderText('Auth user'); self.auth_pass=QLineEdit(); self.auth_pass.setPlaceholderText('Auth pass'); self.cookies_file=QLineEdit(); self.cookies_file.setPlaceholderText('cookies.txt'); self.chk_import_browser_cookies=QCheckBox('Import Browser Cookies'); cr=QHBoxLayout(); cr.addWidget(self.cookies_file); cbbtn=QPushButton('...'); cr.addWidget(cbbtn); cbbtn.clicked.connect(lambda: self._pick_file(self.cookies_file)); self.plugins_dir=QLineEdit(); self.plugins_dir.setPlaceholderText('Plugins directory'); pr=QHBoxLayout(); pr.addWidget(self.plugins_dir); pbtn=QPushButton('...'); pr.addWidget(pbtn); pbtn.clicked.connect(lambda: self._pick_dir(self.plugins_dir))
        for w in (self.chk_disable_js,self.size_cap,self.throttle,self.auth_user,self.auth_pass,self.chk_import_browser_cookies): misc.addWidget(w)
        misc.addLayout(cr); misc.addLayout(pr); config_v.addWidget(misc)
        config_v.addStretch(1)
        # Right panel
        right=QWidget(); rv=QVBoxLayout(right); rv.setContentsMargins(4,4,4,4); rv.setSpacing(6)
        # Button rows (compact organization):
        # Row 1: Core run controls
        # Row 2: Post-clone / auxiliary actions
        row1=QHBoxLayout(); row1.setSpacing(6)
        self.btn_clone=QPushButton('Clone'); row1.addWidget(self.btn_clone)
        self.btn_estimate=QPushButton('Estimate'); row1.addWidget(self.btn_estimate)
        self.btn_pause=QPushButton('Pause'); self.btn_pause.setEnabled(False); row1.addWidget(self.btn_pause)
        self.btn_cancel=QPushButton('Cancel'); self.btn_cancel.setEnabled(False); row1.addWidget(self.btn_cancel)
        self.btn_wizard=QPushButton('Wizard'); row1.addWidget(self.btn_wizard); self.btn_wizard.setEnabled(False)
        row1.addStretch(1)
        row2=QHBoxLayout(); row2.setSpacing(6)
        self.btn_run_docker=QPushButton('Run Docker'); self.btn_run_docker.setEnabled(False); row2.addWidget(self.btn_run_docker)
        self.btn_serve=QPushButton('Serve Folder'); self.btn_serve.setEnabled(False); row2.addWidget(self.btn_serve)
        self.btn_deps=QPushButton('Dependencies'); row2.addWidget(self.btn_deps)
        self.btn_save_cfg=QPushButton('Save Config'); row2.addWidget(self.btn_save_cfg)
        self.btn_load_cfg=QPushButton('Load Config'); row2.addWidget(self.btn_load_cfg)
        row2.addStretch(1)
        rv.addLayout(row1); rv.addLayout(row2)
        self.prog=QProgressBar(); self.prog.setRange(0,100); rv.addWidget(self.prog)
        self.console=QTextEdit(); self.console.setReadOnly(True); rv.addWidget(self.console,1)
        self.splitter.addWidget(right); self.splitter.setStretchFactor(0,0); self.splitter.setStretchFactor(1,1)
        # Connections
        self.btn_clone.clicked.connect(self.start_clone); self.btn_cancel.clicked.connect(self._cancel_clone); self.btn_estimate.clicked.connect(self._estimate_items); self.btn_deps.clicked.connect(self._show_deps_dialog)
        self.btn_pause.clicked.connect(self._toggle_pause); self.btn_run_docker.clicked.connect(self._run_docker_image); self.btn_serve.clicked.connect(self._serve_folder)
        self.btn_wizard.clicked.connect(self._run_wizard)
        # Enable Wizard only when a non-empty URL is present
        def _update_wizard_enabled(txt:str):
            self.btn_wizard.setEnabled(bool(txt.strip()))
        self.url_in.textChanged.connect(_update_wizard_enabled)
        # Initialize state based on any pre-populated URL (e.g., history load)
        _update_wizard_enabled(self.url_in.text())
        self.btn_save_cfg.clicked.connect(self._save_profile_dialog)
        self.btn_load_cfg.clicked.connect(self._load_profile_dialog)
        self._load_history()
        bar=QHBoxLayout(); bar.setSpacing(12); self.status_lbl=QLabel('Ready.'); self.metric_lbl=QLabel(''); self.phase_time_lbl=QLabel(''); bar.addWidget(self.status_lbl,1); bar.addWidget(self.metric_lbl,2); bar.addWidget(self.phase_time_lbl,2); root.addLayout(bar)
        self._compute_and_lock_min_size()
        # Apply descriptive tooltips to all interactive widgets
        self._apply_tooltips()
        # Normalize button appearance (uniform sizing / padding)
        self._normalize_buttons()

    # Helpers
    def _browse_dest(self):
        p=QFileDialog.getExistingDirectory(self,'Select Destination');
        if p: self.dest_in.setText(p)
    def _pick_file(self, target: QLineEdit):
        p,_=QFileDialog.getOpenFileName(self,'Select File');
        if p: target.setText(p)
    def _pick_dir(self, target: QLineEdit):
        p=QFileDialog.getExistingDirectory(self,'Select Directory');
        if p: target.setText(p)

    def _connect_signals(self):
        self.sig_log.connect(self._on_log); self.sig_phase.connect(self._on_phase); self.sig_bandwidth.connect(lambda r: self._update_metric(rate=r)); self.sig_api.connect(lambda n: self._update_metric(api=n)); self.sig_router.connect(lambda n: self._update_metric(router=n)); self.sig_checksum.connect(lambda p: self._update_metric(chk=p))

    def _apply_tooltips(self):  # Centralized tooltips for clarity & maintainability
        tt={
            'url_in':"Root website URL to clone (include scheme, e.g. https://example.com).",
            'dest_in':"Local folder where the cloned site (and optionally Docker build context) will be written.",
            'name_in':"Docker image/name tag to use when building/running the container.",
            'ip_in':"Interface/IP to bind for serving or container port mapping (default 127.0.0.1).",
            'host_port':"Host port exposed for Docker run / local serve.",
            'cont_port':"Internal container port the app/site will listen on inside Docker (default 80).",
            'chk_build':"Build a Docker image after cloning (produces a runnable container).",
            'chk_run_built':"After successful build, immediately run the Docker container in detached mode.",
            'chk_serve':"Serve the output folder with a lightweight HTTP server (no Docker).",
            'chk_open_browser':"Open the default web browser after starting serve/run.",
            'chk_incremental':"Enable wget incremental (-N): only download resources that are newer / changed since last run.",
            'chk_diff':"After clone, compute diff vs previous state to produce change summary.",
            'chk_estimate_first':"Before cloning, perform a quick spider to estimate total items (can refine decisions).",
            'chk_cleanup':"Remove intermediate build artifacts (keeps output clean).",
            'chk_prerender':"Use Playwright (headless Chromium) to render dynamic pages / SPAs before snapshotting (slower, more complete).",
            'spin_prer_pages':"Maximum dynamic pages to prerender (caps exploration to avoid runaway crawling).",
            'chk_capture_api':"Capture JSON / API responses encountered during prerender for offline reproduction.",
            'hook_in':"Optional Python hook script executed for advanced customization (e.g. tweaking manifest).",
            'chk_router':"Intercept client-side navigation (history/pushState) to enumerate additional SPA routes.",
            'chk_route_hash':"Include hash fragment (#) as distinct route during interception.",
            'chk_router_quiet':"Suppress per-route log spam while still counting routes.",
            'spin_router_max':"Upper bound on total discovered routes (safety limit).",
            'spin_router_settle':"Milliseconds to wait after navigation for network/DOM to stabilize before capture.",
            'router_wait_sel':"CSS selector to wait for before considering a SPA route fully rendered (blank to skip).",
            'router_allow':"Comma-separated regex patterns; only matching routes are kept (applied before deny).",
            'router_deny':"Comma-separated regex patterns to exclude routes (evaluated after allow).",
            'chk_checksums':"Compute file checksums (hashes) for integrity tracking.",
            'chk_verify_after':"Immediately verify the generated site contents against recorded checksums.",
            'chk_verify_deep':"Deep verification (may re-hash more aggressively / nested content).",
            'checksum_ext':"Extra file extensions (comma separated) to include in checksum set (e.g. css,js,png).",
            'chk_disable_js':"Strip <script> tags from output for hardened static snapshot (may break interactivity).",
            'size_cap':"Total download size hard cap (e.g. 500M, 2G). Empty = unlimited.",
            'throttle':"Limit download bandwidth (e.g. 2M for ~2 megabytes/second).",
            'auth_user':"HTTP Basic Auth username (if site requires).",
            'auth_pass':"HTTP Basic Auth password (if site requires).",
            'cookies_file':"Path to Netscape format cookies.txt to inject during clone/prerender.",
            'chk_import_browser_cookies':"Attempt to import cookies from installed browsers for the target domain.",
            'plugins_dir':"Directory containing plugin Python files (loaded to extend pipeline phases).",
            'btn_clone':"Start the cloning pipeline with current configuration.",
            'btn_estimate':"Estimate approximate number of URLs/resources via lightweight spider.",
            'btn_pause':"Pause / resume the active clone (cooperative between phases).",
            'btn_cancel':"Request cooperative cancellation; current phase will attempt graceful stop.",
            'btn_wizard':"Analyze the site heuristically and propose recommended dynamic / integrity options.",
            'btn_run_docker':"Run the previously built Docker image (detached).",
            'btn_serve':"Start/stop a simple HTTP server hosting the last successful output folder.",
            'btn_deps':"Show installed / missing optional dependencies with install hints (commands copied to clipboard).",
            'btn_save_cfg':"Save current settings as a reusable profile (stored in ~/.cw2dt_profiles).",
            'btn_load_cfg':"Load a previously saved profile and apply its settings.",
            'console':"Log output, progress messages, structured event summaries, and diagnostics.",
        }
        for name,text in tt.items():
            w=getattr(self,name,None)
            if w is not None:
                try: w.setToolTip(text)
                except Exception: pass
        # Add composite clarifications
        if hasattr(self,'status_lbl'):
            self.status_lbl.setToolTip('High-level status and current weighted phase progress.')
        if hasattr(self,'metric_lbl'):
            self.metric_lbl.setToolTip('Inline live metrics: bandwidth, routes discovered, API captures, checksum progress, etc.')
        if hasattr(self,'phase_time_lbl'):
            self.phase_time_lbl.setToolTip('Elapsed time per completed phase (auto-updated).')

    def _normalize_buttons(self):
        """Ensure all primary QPushButtons share consistent min size and padding.
        Keeps visual rhythm across rows without hard-locking dynamic resize behavior."""
        buttons=[getattr(self,n) for n in (
            'btn_clone','btn_estimate','btn_pause','btn_cancel','btn_wizard',
            'btn_run_docker','btn_serve','btn_deps','btn_save_cfg','btn_load_cfg'
        ) if hasattr(self,n)]
        if not buttons: return
        # Determine a reasonable min width (longest text + padding heuristic)
        fm=self.fontMetrics()
        max_text_w=max(fm.horizontalAdvance(b.text()) for b in buttons)+28  # padding allowance
        target_w=min(max(110, max_text_w), 220)  # clamp upper bound to avoid overly wide buttons
        for b in buttons:
            try:
                b.setMinimumHeight(32)
                b.setMinimumWidth(target_w)
                b.setIconSize(QSize(16,16))
            except Exception:
                pass
        # Apply a light stylesheet only to these buttons (avoid QToolButton toggles)
        style="""
QPushButton {
  padding:4px 10px;
  font-weight:500;
  border:1px solid #5a5a5a;
  border-radius:4px;
  background:#2e2e2e;
  color:#f0f0f0;
}
QPushButton:hover { background:#3a3a3a; }
QPushButton:pressed { background:#444; }
QPushButton:disabled { background:#2e2e2e; color:#888; border-color:#3a3a3a; }
"""
        # Merge with any existing stylesheet on the root widget
        prev=self.styleSheet() or ''
        if 'QPushButton' not in prev:  # avoid duplicating if already applied
            self.setStyleSheet(prev + ('\n' if prev else '') + style)

    def _update_dependency_banner(self):
        msgs=[]
        if not is_wget2_available(): msgs.append('wget2 missing')
        if self.chk_build.isChecked() and not docker_available(): msgs.append('docker missing')
        if msgs: self.status_lbl.setText(' / '.join(msgs))

    # ------------------- Profiles (Save / Load) -------------------
    def _profiles_dir(self):
        d=os.path.join(os.path.expanduser('~'), '.cw2dt_profiles')
        try: os.makedirs(d, exist_ok=True)
        except Exception: pass
        return d
    def _current_profile_dict(self):
        return {
            'url': self.url_in.text().strip(), 'dest': self.dest_in.text().strip(), 'docker_name': self.name_in.text().strip(),
            'bind_ip': self.ip_in.text().strip(), 'host_port': self.host_port.value(), 'container_port': self.cont_port.value(),
            'build': self.chk_build.isChecked(), 'run_built': self.chk_run_built.isChecked(), 'serve_folder': self.chk_serve.isChecked(),
            'open_browser': self.chk_open_browser.isChecked(), 'incremental': self.chk_incremental.isChecked(), 'diff': self.chk_diff.isChecked(),
            'estimate_first': self.chk_estimate_first.isChecked(), 'cleanup': self.chk_cleanup.isChecked(),
            'prerender': self.chk_prerender.isChecked(), 'prerender_max_pages': self.spin_prer_pages.value(), 'capture_api': self.chk_capture_api.isChecked(), 'hook_script': self.hook_in.text().strip(),
            'router_intercept': self.chk_router.isChecked(), 'router_include_hash': self.chk_route_hash.isChecked(), 'router_quiet': self.chk_router_quiet.isChecked(),
            'router_max_routes': self.spin_router_max.value(), 'router_settle_ms': self.spin_router_settle.value(), 'router_wait_selector': self.router_wait_sel.text().strip(),
            'router_allow': self.router_allow.text().strip(), 'router_deny': self.router_deny.text().strip(),
            'checksums': self.chk_checksums.isChecked(), 'verify_after': self.chk_verify_after.isChecked(), 'verify_deep': self.chk_verify_deep.isChecked(), 'checksum_ext': self.checksum_ext.text().strip(),
            'disable_js': self.chk_disable_js.isChecked(), 'size_cap': self.size_cap.text().strip(), 'throttle': self.throttle.text().strip(),
            'auth_user': self.auth_user.text().strip(), 'auth_pass': self.auth_pass.text().strip(), 'cookies_file': self.cookies_file.text().strip(), 'import_browser_cookies': self.chk_import_browser_cookies.isChecked(),
            'plugins_dir': self.plugins_dir.text().strip()
        }
    def _apply_profile_dict(self, data: dict):
        try:
            self.url_in.setText(data.get('url',''))
            self.dest_in.setText(data.get('dest',''))
            self.name_in.setText(data.get('docker_name',''))
            self.ip_in.setText(data.get('bind_ip','127.0.0.1'))
            self.host_port.setValue(int(data.get('host_port',8080)))
            self.cont_port.setValue(int(data.get('container_port',80)))
            self.chk_build.setChecked(bool(data.get('build')))
            self.chk_run_built.setChecked(bool(data.get('run_built')))
            self.chk_serve.setChecked(bool(data.get('serve_folder')))
            self.chk_open_browser.setChecked(bool(data.get('open_browser')))
            self.chk_incremental.setChecked(bool(data.get('incremental')))
            self.chk_diff.setChecked(bool(data.get('diff')))
            self.chk_estimate_first.setChecked(bool(data.get('estimate_first')))
            self.chk_cleanup.setChecked(bool(data.get('cleanup')))
            self.chk_prerender.setChecked(bool(data.get('prerender')))
            self.spin_prer_pages.setValue(int(data.get('prerender_max_pages',40)))
            self.chk_capture_api.setChecked(bool(data.get('capture_api')))
            self.hook_in.setText(data.get('hook_script',''))
            self.chk_router.setChecked(bool(data.get('router_intercept')))
            self.chk_route_hash.setChecked(bool(data.get('router_include_hash')))
            self.chk_router_quiet.setChecked(bool(data.get('router_quiet')))
            self.spin_router_max.setValue(int(data.get('router_max_routes',200)))
            self.spin_router_settle.setValue(int(data.get('router_settle_ms',350)))
            self.router_wait_sel.setText(data.get('router_wait_selector',''))
            self.router_allow.setText(data.get('router_allow',''))
            self.router_deny.setText(data.get('router_deny',''))
            self.chk_checksums.setChecked(bool(data.get('checksums')))
            self.chk_verify_after.setChecked(bool(data.get('verify_after')))
            self.chk_verify_deep.setChecked(bool(data.get('verify_deep')))
            self.checksum_ext.setText(data.get('checksum_ext',''))
            self.chk_disable_js.setChecked(bool(data.get('disable_js')))
            self.size_cap.setText(data.get('size_cap',''))
            self.throttle.setText(data.get('throttle',''))
            self.auth_user.setText(data.get('auth_user',''))
            self.auth_pass.setText(data.get('auth_pass',''))
            self.cookies_file.setText(data.get('cookies_file',''))
            self.chk_import_browser_cookies.setChecked(bool(data.get('import_browser_cookies')))
            self.plugins_dir.setText(data.get('plugins_dir',''))
            # Refresh wizard availability after loading profile
            try:
                self.btn_wizard.setEnabled(bool(self.url_in.text().strip()))
            except Exception:
                pass
        except Exception as e:
            QMessageBox.warning(self,'Profile Load','Failed to apply profile: '+str(e))
    def _save_profile_dialog(self):
        from PySide6.QtWidgets import QInputDialog
        prof=self._current_profile_dict()
        suggested=self.name_in.text().strip() or 'profile'
        name,ok=QInputDialog.getText(self,'Save Profile','Profile name:', text=suggested)
        if not ok or not name.strip(): return
        safe=re.sub(r'[^a-zA-Z0-9_.-]+','_', name.strip())
        path=os.path.join(self._profiles_dir(), safe+'.json')
        try:
            import json
            with open(path,'w',encoding='utf-8') as f: json.dump(prof,f,indent=2)
            self._on_log(f"[profile] saved {path}")
        except Exception as e:
            QMessageBox.warning(self,'Save Failed', str(e))
    def _load_profile_dialog(self):
        d=self._profiles_dir()
        files=[f for f in os.listdir(d) if f.endswith('.json')]
        if not files:
            QMessageBox.information(self,'Profiles','No profiles saved yet.')
            return
        from PySide6.QtWidgets import QInputDialog
        name,ok=QInputDialog.getItem(self,'Load Profile','Select profile:', files, 0, False)
        if not ok or not name: return
        path=os.path.join(d,name)
        try:
            import json
            data=json.load(open(path,'r',encoding='utf-8'))
            self._apply_profile_dict(data)
            self._on_log(f"[profile] loaded {name}")
        except Exception as e:
            QMessageBox.warning(self,'Load Failed', str(e))

    # ------------------- Wizard (Recommendation) -------------------
    def _scan_site_features(self, url: str, timeout: float=6.0) -> dict:
        """Fetch root page and run lightweight heuristics to recommend settings.
        Heuristics:
          - Detect SPA / frameworks (react/vue/angular/next/nuxt) -> enable prerender + router intercept.
          - Detect large script count (>15) -> recommend prerender (dynamic) OR suggest JS stripping (optional) if hardening.
          - If inline JSON blobs / hydration markers found -> prerender.
          - If page size < 35KB and few scripts -> static (no prerender needed).
        """
        import urllib.request, urllib.error
        info={'fetched':False,'error':None,'size':0,'scripts':0,'frameworks':[], 'recommend':{}}
        try:
            req=urllib.request.Request(url, headers={'User-Agent':'cw2dt-wizard/1.0'})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw=resp.read(250_000)  # cap at 250KB
            info['fetched']=True; info['size']=len(raw)
            try:
                text=raw.decode('utf-8','ignore')
            except Exception:
                text=''
            import re
            script_tags=re.findall(r'<script\b', text, re.IGNORECASE)
            info['scripts']=len(script_tags)
            fw_patterns={
                'react': r'react[^a-zA-Z0-9]|data-reactroot|__REACT_DEVTOOLS_GLOBAL_HOOK__',
                'vue': r'vue(?:\.runtime)?\.js|__VUE_DEVTOOLS_GLOBAL_HOOK__',
                'angular': r'ng-version="|angular[^a-zA-Z0-9]',
                'nextjs': r'__NEXT_DATA__|next/dist',
                'nuxt': r'__NUXT__',
                'svelte': r'svelte[^a-zA-Z0-9]|data-svelte',
            }
            found=[]
            for name,pat in fw_patterns.items():
                if re.search(pat, text): found.append(name)
            info['frameworks']=found
            rec=info['recommend']
            dynamic = bool(found) or (info['scripts']>15) or ('__NEXT_DATA__' in text or '__NUXT__' in text)
            if dynamic:
                rec['prerender']=True
                if any(f in found for f in ('react','vue','nextjs','nuxt','angular','svelte')):
                    rec['router_intercept']=True
            if info['size']<35_000 and info['scripts']<=4 and not found:
                rec['prerender']=False
            # If many external scripts but no frameworks, still consider prerender
            if info['scripts']>25 and not found:
                rec['prerender']=True
            return info
        except Exception as e:
            info['error']=str(e)
            return info
    def _run_wizard(self):
        """Two-phase wizard: (1) Scan (dry-run heuristics) (2) Results with Apply/Cancel.
        If running in offscreen test mode, run synchronously for deterministic tests."""
        url=self.url_in.text().strip()
        if not url:
            QMessageBox.information(self,'Wizard','Enter a URL first.')
            return
        # Inner function to gather extended analysis (can be moved to thread)
        def _extended_analysis(u: str):
            info=self._scan_site_features(u)
            # Add spider estimate (best effort)
            try:
                from cw2dt_core import estimate_site_items
                info['estimated_items']=estimate_site_items(u)
            except Exception:
                info['estimated_items']=None
            # Heuristic reasons
            reasons=[]
            if info.get('frameworks'): reasons.append('Framework(s): '+','.join(info['frameworks']))
            if info.get('scripts',0)>25: reasons.append('Heavy script usage')
            if info.get('scripts',0)<=4 and not info.get('frameworks'): reasons.append('Likely static (few scripts)')
            if info.get('size',0)<35_000: reasons.append('Small initial payload (<35KB)')
            info['reasons']=reasons
            return info
        # Offscreen test short-circuit
        if os.environ.get('QT_QPA_PLATFORM')=='offscreen':
            info=_extended_analysis(url)
            self._wizard_show_results(info)
            return
        # Build scanning dialog with progress (indeterminate)
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar
        scan_dlg=QDialog(self); scan_dlg.setWindowTitle('Wizard – Scanning')
        v=QVBoxLayout(scan_dlg)
        lbl=L=QLabel(f'Scanning {url}\nFetching & analyzing...'); v.addWidget(lbl)
        bar=QProgressBar(); bar.setRange(0,0); v.addWidget(bar)
        scan_dlg.setModal(True)
        # Use a worker thread
        from PySide6.QtCore import QThread, Signal, QObject
        class _ScanWorker(QObject):
            finished=Signal(dict)
            def run(self):
                data=_extended_analysis(url)
                self.finished.emit(data)
        worker=_ScanWorker(); thread=QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        def _done(data):
            scan_dlg.accept()
            thread.quit(); thread.wait(50)
            self._wizard_show_results(data)
        worker.finished.connect(_done)
        thread.start()
        scan_dlg.exec()

    def _apply_wizard_recommendations(self, info: dict, chk_states: dict):
        # chk_states contains final user-selected booleans for recs
        if chk_states.get('prerender') is not None:
            self.chk_prerender.setChecked(chk_states['prerender'])
        if chk_states.get('router_intercept') is not None:
            self.chk_router.setChecked(chk_states['router_intercept'])
            if chk_states['router_intercept'] and info.get('frameworks'):
                self.chk_route_hash.setChecked(True)
        if chk_states.get('js_strip') is not None:
            self.chk_disable_js.setChecked(chk_states['js_strip'])
        if chk_states.get('checksums') is not None:
            self.chk_checksums.setChecked(chk_states['checksums'])
            self.chk_verify_after.setChecked(chk_states['checksums'])
        if chk_states.get('incremental') is not None:
            self.chk_incremental.setChecked(chk_states['incremental'])
            self.chk_diff.setChecked(chk_states['incremental'])
        self._on_log('[wizard] applied recommendations')

    def _wizard_show_results(self, info: dict):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox, QCheckBox, QHBoxLayout, QFrame
        dlg=QDialog(self); dlg.setWindowTitle('Wizard – Results')
        lay=QVBoxLayout(dlg)
        if info.get('error'):
            lay.addWidget(QLabel('Fetch error: '+info['error']))
        else:
            summary=f"Fetched {info['size']} bytes • scripts={info['scripts']} • frameworks={','.join(info['frameworks']) or 'none'}"
            if info.get('estimated_items') is not None:
                summary += f" • est items={info['estimated_items']}"
            lay.addWidget(QLabel(summary))
            if info.get('reasons'):
                lay.addWidget(QLabel('Heuristics: '+ '; '.join(info['reasons'])))
        rec=info.get('recommend',{})
        # Checkbox panel
        chk_prer=QCheckBox('Enable prerender (dynamic rendering)'); chk_prer.setChecked(rec.get('prerender', self.chk_prerender.isChecked()))
        chk_router=QCheckBox('Enable router interception (SPA routes)'); chk_router.setChecked(rec.get('router_intercept', self.chk_router.isChecked()))
        chk_js=QCheckBox('Strip JavaScript (harden output)'); chk_js.setChecked(self.chk_disable_js.isChecked())
        chk_checksums=QCheckBox('Checksums + verify integrity'); chk_checksums.setChecked(self.chk_checksums.isChecked() or self.chk_verify_after.isChecked())
        chk_incremental=QCheckBox('Incremental + diff state tracking'); chk_incremental.setChecked(self.chk_incremental.isChecked() or self.chk_diff.isChecked())
        for w in (chk_prer, chk_router, chk_js, chk_checksums, chk_incremental): lay.addWidget(w)
        sep=QFrame(); sep.setFrameShape(QFrame.Shape.HLine); lay.addWidget(sep)
        bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Close)
        lay.addWidget(bb)
        applied={'done':False}
        def _apply():
            chk={'prerender':chk_prer.isChecked(),'router_intercept':chk_router.isChecked(),'js_strip':chk_js.isChecked(),'checksums':chk_checksums.isChecked(),'incremental':chk_incremental.isChecked()}
            self._apply_wizard_recommendations(info, chk)
            applied['done']=True
        bb.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(_apply)
        bb.rejected.connect(dlg.reject)
        bb.accepted.connect(_apply)
        dlg.exec()

    def _build_config(self)->CloneConfig:
        cfg = CloneConfig(
            url=self.url_in.text().strip(), dest=self.dest_in.text().strip(), docker_name=self.name_in.text().strip() or 'site',
            build=self.chk_build.isChecked(), bind_ip=self.ip_in.text().strip() or '127.0.0.1', host_port=self.host_port.value(), container_port=self.cont_port.value(),
            size_cap=self.size_cap.text().strip() or None, throttle=self.throttle.text().strip() or None,
            auth_user=self.auth_user.text().strip() or None, auth_pass=self.auth_pass.text().strip() or None,
            cookies_file=self.cookies_file.text().strip() or None, import_browser_cookies=self.chk_import_browser_cookies.isChecked(), disable_js=self.chk_disable_js.isChecked(),
            prerender=self.chk_prerender.isChecked(), prerender_max_pages=self.spin_prer_pages.value(), capture_api=self.chk_capture_api.isChecked(), hook_script=self.hook_in.text().strip() or None,
            rewrite_urls=True, router_intercept=self.chk_router.isChecked(), router_include_hash=self.chk_route_hash.isChecked(), router_max_routes=self.spin_router_max.value(), router_settle_ms=self.spin_router_settle.value(), router_wait_selector=self.router_wait_sel.text().strip() or None,
            router_allow=[p.strip() for p in self.router_allow.text().split(',') if p.strip()] or None, router_deny=[p.strip() for p in self.router_deny.text().split(',') if p.strip()] or None, router_quiet=self.chk_router_quiet.isChecked(),
            no_manifest=False, checksums=self.chk_checksums.isChecked(), checksum_ext=self.checksum_ext.text().strip() or None, verify_after=self.chk_verify_after.isChecked(), verify_deep=self.chk_verify_deep.isChecked(),
            incremental=self.chk_incremental.isChecked(), diff_latest=self.chk_diff.isChecked(), plugins_dir=self.plugins_dir.text().strip() or None, json_logs=False, profile=False,
            open_browser=self.chk_open_browser.isChecked(), run_built=self.chk_run_built.isChecked(), serve_folder=self.chk_serve.isChecked(), estimate_first=self.chk_estimate_first.isChecked()
        )
        setattr(cfg,'cleanup', self.chk_cleanup.isChecked())
        return cfg
    def start_clone(self):
        # original validation logic remains
        allow_raw=self.router_allow.text().strip(); deny_raw=self.router_deny.text().strip(); bad=[]; import re as _re
        for label,raw in (('allow',allow_raw),('deny',deny_raw)):
            if not raw: continue
            for pat in [p.strip() for p in raw.split(',') if p.strip()]:
                try: _re.compile(pat)
                except Exception as e: bad.append(f"{label}:{pat} -> {e}")
        if bad: QMessageBox.warning(self,'Regex Error','Invalid router pattern(s):\n'+'\n'.join(bad)); return
        cfg=self._build_config(); errs=validate_required_fields(cfg.url,cfg.dest,cfg.bind_ip,cfg.build,cfg.docker_name)
        if errs: QMessageBox.warning(self,'Validation','\n'.join(errs)); return
        if port_in_use(cfg.bind_ip,int(cfg.host_port)):
            QMessageBox.warning(self,'Port In Use',f'Host port {cfg.host_port} already in use.'); return
        if cfg.build and not docker_available(): QMessageBox.warning(self,'Docker Missing','Docker is not available.'); return
        self.console.clear(); self._set_running(True); self._paused=False; self.btn_pause.setText('Pause')
        cb=_GuiCallbacks(self); self.worker=_CloneWorker(cfg,cb); self._init_weighting(cfg); self.worker.finished.connect(self._clone_finished); self.worker.start(); self._on_log('[gui] clone started')

    def _cancel_clone(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel(); self._on_log('[gui] cancel requested (cooperative)')

    def _clone_finished(self, result):
        self._on_log('[gui] clone finished'); self._set_running(False); self._last_result=result
        if result and getattr(result,'success',False):
            self.status_lbl.setText('Clone SUCCESS'); self._save_history(); self.btn_run_docker.setEnabled(True); self.btn_serve.setEnabled(True)
        else:
            self.status_lbl.setText('Clone FAILED')
        if result and getattr(result,'output_folder',None): self.console.append(f"Output: {result.output_folder}")

    def _on_log(self,msg:str):
        # Attempt to parse JSON events to surface structured info
        if msg.startswith('{') and msg.endswith('}'):  # fast path
            try:
                evt=json.loads(msg)
                et=evt.get('event')
                if et=='diff_summary':
                    a=evt.get('added'); r=evt.get('removed'); m=evt.get('modified'); u=evt.get('unchanged')
                    self.console.append(f"[diff] added={a} removed={r} modified={m} unchanged={u}")
                    sa=evt.get('sample_added') or []
                    sm=evt.get('sample_modified') or []
                    if sa: self.console.append('  sample added: '+', '.join(sa))
                    if sm: self.console.append('  sample modified: '+', '.join(sm))
                elif et=='verify':
                    self.console.append(f"[verify] passed={'YES' if evt.get('passed') else 'NO'}")
                elif et=='canceled':
                    self.console.append(f"[cancel] user canceled during {evt.get('phase')}")
                elif et=='plugin_finalize_error':
                    self.console.append(f"[plugin] finalize error {evt.get('name')}: {evt.get('error')}")
                elif et=='plugin_loaded':
                    self.console.append(f"[plugin] loaded {evt.get('name')}")
                elif et=='plugin_load_failed':
                    self.console.append(f"[plugin] load failed {evt.get('name')}: {evt.get('error')}")
                elif et=='timings':
                    # Build a compact timings table
                    keys=[k for k in evt.keys() if k.endswith('_seconds') and k!='total_seconds']
                    if keys:
                        rows=[f"  {k.replace('_seconds','')}: {evt[k]}s" for k in sorted(keys)]
                        if evt.get('total_seconds') is not None:
                            rows.append(f"  total: {evt.get('total_seconds')}s")
                        self.console.append('[timings]\n'+'\n'.join(rows))
                # fall through still prints raw JSON for transparency
            except Exception:
                pass
        self.console.append(msg); self.console.ensureCursorVisible()
    def _on_phase(self,phase:str,pct:int): self._update_weighted_progress(phase,pct)
    def _update_metric(self,rate=None,api=None,router=None,chk=None):
        parts=[]
        if rate: parts.append(f'Rate {rate}')
        if api is not None: parts.append(f'API {api}')
        if router is not None: parts.append(f'Routes {router}')
        if chk is not None: parts.append(f'Checksums {chk}%')
        self.metric_lbl.setText(' | '.join(parts))
        done=[f"{ph}:{self._phase_end[ph]-st:.1f}s" for ph,st in self._phase_start.items() if ph in self._phase_end]
        if done: self.phase_time_lbl.setText(' | '.join(done))
    def _toggle_pause(self):
        if not self.worker or not self.worker.isRunning(): return
        self._paused=not self._paused
        self.btn_pause.setText('Resume' if self._paused else 'Pause')
        self._on_log('[gui] paused' if self._paused else '[gui] resumed')
    def _run_docker_image(self):
        if not self._last_result or not getattr(self._last_result,'success',False): return
        name=self.name_in.text().strip() or 'site'
        try:
            import subprocess
            cmd=['docker','run','-d','-p',f"{self.host_port.value()}:{self.cont_port.value()}",name]
            self._on_log('[gui] running docker: '+' '.join(cmd))
            subprocess.Popen(cmd)
        except Exception as e:
            self._on_log(f'[gui] docker run failed: {e}')
    def _serve_folder(self):
        # Toggle behavior: start if not running, else stop
        if self._serve_httpd is None:
            if not self._last_result or not getattr(self._last_result,'output_folder',None): return
            folder=self._last_result.output_folder
            try:
                import threading, http.server, socketserver
                ip=self.ip_in.text().strip() or '127.0.0.1'; port=self.host_port.value()
                class _Handler(http.server.SimpleHTTPRequestHandler):
                    def __init__(self,*a,**k): os.chdir(folder); super().__init__(*a,**k)
                def _run():
                    try:
                        with socketserver.TCPServer((ip, port), _Handler) as httpd:
                            self._serve_httpd=httpd
                            self._on_log(f'[serve] http://{ip}:{port} -> {folder}')
                            try:
                                from PySide6.QtWidgets import QMessageBox
                                QMessageBox.information(self,'Serve Started',f'Serving {folder}\nhttp://{ip}:{port}')
                            except Exception: pass
                            httpd.serve_forever()
                    except Exception as e:
                        self._on_log(f'[serve] failed: {e}')
                    finally:
                        self._serve_httpd=None; self._serve_thread=None
                        try:
                            from PySide6.QtWidgets import QMessageBox
                            QMessageBox.information(self,'Serve Stopped','Folder serving stopped.')
                        except Exception: pass
                self._serve_thread=threading.Thread(target=_run,daemon=True); self._serve_thread.start(); self.btn_serve.setText('Stop Serve')
            except Exception as e:
                self._on_log(f'[serve] failed: {e}')
        else:
            try:
                self._serve_httpd.shutdown()
            except Exception:
                pass
            self._serve_httpd=None
            self._on_log('[serve] shutdown requested')
            self.btn_serve.setText('Serve Folder')

    def _set_running(self,running:bool):
        self.btn_clone.setEnabled(not running); self.btn_cancel.setEnabled(running); self.btn_estimate.setEnabled(not running); self.btn_pause.setEnabled(running)
        for w in (self.chk_build,self.chk_run_built,self.chk_serve,self.chk_open_browser,self.chk_prerender): w.setEnabled(not running)
        if running: self.btn_run_docker.setEnabled(False); self.btn_serve.setEnabled(False)

    def _compute_and_lock_min_size(self):
        # Expand all to measure widest required width
        states=[box._toggle.isChecked() for box in self._sections]
        for box in self._sections:
            if not box._toggle.isChecked():
                box._toggle.setChecked(True); box._on_toggled()
        QApplication.processEvents()
        # Measure underlying content width, not the scroll area compressed size
        content_w=self._config_container.sizeHint().width()
        # Add some padding + scrollbar reserve
        pad=24
        left_needed=content_w+pad
        # Measure right side size hint after it has laid out
        right_hint=self.splitter.widget(1).sizeHint()
        right_w=right_hint.width()
        right_h=right_hint.height()
        # Compute full window width and target height (but allow height flexibility)
        total_w=left_needed+right_w+40
        content_h=max(self._config_container.sizeHint().height(), right_h)+120
        # Cap height to available screen (leave margin) so window doesn't go off-screen
        screen=QApplication.primaryScreen(); avail_h=screen.availableGeometry().height() if screen else 1000
        cap_h=min(content_h, max(600, avail_h-120))
        # Establish a global MINIMUM width but allow user to expand window to the right.
        # Left panel width is fixed (min==max) so resizing only affects the right pane / console.
        self.setMinimumWidth(total_w)
        self.setMinimumHeight(min(600, cap_h))
        # Resize to capped height if current greater
        self.resize(total_w, cap_h)
        # Set left fixed width so center position stays constant
        self.splitter.widget(0).setMinimumWidth(left_needed)
        self.splitter.widget(0).setMaximumWidth(left_needed)
        # Ensure splitter allocates sizes explicitly
        self.splitter.setSizes([left_needed, right_w])
        # Restore previous collapse states
        for st,box in zip(states,self._sections):
            if not st:
                box._toggle.setChecked(False); box._on_toggled()

    def showEvent(self, ev):  # ensure fixation after initial layout on different DPI
        super().showEvent(ev)
        if not getattr(self,'_fixed_sized',False):
            try:
                self._compute_and_lock_min_size()
            except Exception:
                pass
            self._fixed_sized=True
        # Initialize anchor after first show when final position is known
        if self._anchor_left is None:
            self._anchor_left=self.x()
            self._last_size=self.size()

    def resizeEvent(self, ev):
        prev_size=self._last_size
        super().resizeEvent(ev)
        # Enforce left edge anchor: if width changed and x shifted, move back
        if self._anchor_left is None:
            self._anchor_left=self.x()
        if prev_size and (self.width()!=prev_size.width()):
            if self.x()!=self._anchor_left:
                # Keep top-left anchored, effectively making right edge the resize handle
                self.move(self._anchor_left, self.y())
        self._last_size=self.size()

    def moveEvent(self, ev):
        # Allow normal moves (user dragging window) when size not changing
        # Update anchor to new x so future resizes still grow/shrink from right edge relative to new position.
        if self._last_size and self.size()==self._last_size:
            self._anchor_left=self.x()
        super().moveEvent(ev)

    def _history_path(self): return os.path.join(os.path.expanduser('~'),'.cw2dt_history.json')
    def _load_history(self):
        try:
            p=self._history_path()
            if os.path.exists(p):
                data=json.load(open(p,'r',encoding='utf-8'))
                urls=data.get('urls') or []
                if urls:
                    self.url_in.setText(urls[0])
                    box=QComboBox(); box.addItems(urls); box.currentTextChanged.connect(lambda t: self.url_in.setText(t))
                    lay=QHBoxLayout(); lay.addWidget(QLabel('Recent:')); lay.addWidget(box)
                    host=self.splitter.widget(0)
                    # If scroll area, insert into its widget layout
                    # (History combo is currently omitted from collapsible arrangement for simplicity.)
        except Exception:
            pass
    def _save_history(self):
        try:
            p=self._history_path(); existing=[]
            if os.path.exists(p):
                try: existing=json.load(open(p,'r',encoding='utf-8')).get('urls') or []
                except Exception: existing=[]
            cur=self.url_in.text().strip()
            if cur: existing=[cur]+[u for u in existing if u!=cur]
            json.dump({'urls':existing[:10]}, open(p,'w',encoding='utf-8'), indent=2)
        except Exception: pass

    def _estimate_items(self):
        from cw2dt_core import estimate_site_items
        url=self.url_in.text().strip()
        if not url: QMessageBox.information(self,'Estimate','Enter a URL first.'); return
        self.status_lbl.setText('Estimating...'); self.repaint(); count=estimate_site_items(url); self.status_lbl.setText(f'Estimate: ~{count} URLs')

    # Dependency helper UI
    def _show_deps_dialog(self):
        optional=[
            ('PySide6','GUI frontend (already required for GUI mode)'),
            ('rich','Rich progress (--progress=rich)'),
            ('playwright','Dynamic prerender (after install run: playwright install chromium)'),
            ('browser_cookie3','Browser cookie import'),
            ('docker','Docker CLI (external)'),
            ('wget2','High-performance mirroring (external)'),
        ]
        import importlib.util, platform, sys as _sys, shutil, subprocess
        from importlib import metadata as _md
        installed=[]; missing=[]
        def _py_version(mod:str):
            # Try importlib.metadata first; fallback to module.__version__
            try:
                return _md.version(mod)
            except Exception:
                try:
                    m=__import__(mod)
                    return getattr(m,'__version__', None)
                except Exception:
                    return None
        def _bin_version(cmd:str):
            try:
                out=subprocess.run([cmd,'--version'],capture_output=True,text=True,timeout=2)
                if out.returncode==0 and out.stdout:
                    first=out.stdout.strip().splitlines()[0]
                    return first[:120]
            except Exception:
                pass
            return None
        for mod,desc in optional:
            if mod in ('docker','wget2'):
                # external binaries
                if shutil.which(mod):
                    installed.append((mod,desc,_bin_version(mod)))
                else:
                    missing.append((mod,desc))
            else:
                spec=importlib.util.find_spec(mod)
                if spec is not None:
                    installed.append((mod,desc,_py_version(mod)))
                else:
                    missing.append((mod,desc))
        py=f"{_sys.executable} -m pip install"
        os_name=platform.system()
        cmds=[]
        py_pkgs=[m for m,_ in missing if m not in ('docker','wget2')]
        if py_pkgs:
            cmds.append(f"{py} {' '.join(py_pkgs)}")
            if 'playwright' in py_pkgs:
                cmds.append("playwright install chromium")
        # OS suggestions for external tools
        def _detect_pkg_mgrs():
            mgrs=[]
            for cand in ('apt-get','dnf','yum','pacman','zypper','apk','brew','winget','choco','port'):  # port = MacPorts
                if shutil.which(cand): mgrs.append(cand)
            return mgrs
        mgrs=_detect_pkg_mgrs()
        def _suggest_external(name:str):
            if name=='wget2':
                if 'brew' in mgrs: return 'brew install wget2'
                if 'apt-get' in mgrs: return 'sudo apt-get update && sudo apt-get install -y wget2'
                if 'dnf' in mgrs: return 'sudo dnf install -y wget2'
                if 'yum' in mgrs: return 'sudo yum install -y wget2'
                if 'pacman' in mgrs: return 'sudo pacman -S --noconfirm wget2'
                if 'zypper' in mgrs: return 'sudo zypper install -y wget2'
                if 'apk' in mgrs: return 'sudo apk add wget2'
                if os_name=='Windows' and 'winget' in mgrs: return 'winget install GnuWin32.Wget'
                return 'Install wget2 manually for your distro'
            if name=='docker':
                if 'brew' in mgrs: return 'brew install --cask docker'
                if 'apt-get' in mgrs: return 'sudo apt-get install -y docker.io'
                if 'dnf' in mgrs: return 'sudo dnf install -y docker'
                if 'yum' in mgrs: return 'sudo yum install -y docker'
                if 'pacman' in mgrs: return 'sudo pacman -S --noconfirm docker'
                if 'zypper' in mgrs: return 'sudo zypper install -y docker'
                if 'apk' in mgrs: return 'sudo apk add docker'
                if os_name=='Windows' and 'winget' in mgrs: return 'winget install Docker.DockerDesktop'
                return 'Install Docker manually for your platform'
            return None
        if any(m=='wget2' for m,_ in missing):
            cmds.append(_suggest_external('wget2'))
        if any(m=='docker' for m,_ in missing):
            cmds.append(_suggest_external('docker'))
        summary_lines=["== Dependency Status =="]
        if installed:
            summary_lines.append('Installed:')
            for m,d,ver in installed:
                vtxt=f" (v{ver})" if ver else ''
                summary_lines.append(f"  - {m}: {d}{vtxt}")
        if missing:
            summary_lines.append('Missing:')
            summary_lines.extend(f"  - {m}: {d}" for m,d in missing)
        if cmds:
            summary_lines.append('\nSuggested Install Commands:')
            summary_lines.extend(f"  {c}" for c in cmds)
        text='\n'.join(summary_lines)
        # Copy commands to clipboard if any
        if cmds:
            try:
                cb=QApplication.clipboard(); cb.setText('\n'.join(cmds))
            except Exception:
                pass
        # Log to console window
        for line in text.splitlines():
            self._on_log(f"[deps] {line}")
        QMessageBox.information(self,'Dependencies', text if len(text)<1200 else text[:1200]+'...')
        self._update_dependency_banner()

    # Weighted progress
    def _init_weighting(self,cfg:CloneConfig):
        weights={}
        cleanup_enabled = bool(getattr(cfg,'cleanup',False))
        if cfg.build:
            if cfg.prerender and cfg.checksums:
                weights={'clone':0.50,'prerender':0.15,'checksums':0.05,'build':0.20,'verify':0.05 if cfg.verify_after else 0,'cleanup':0.05 if cleanup_enabled else 0}
            elif cfg.prerender:
                weights={'clone':0.48,'prerender':0.15,'build':0.27,'verify':0.05 if cfg.verify_after else 0,'cleanup':0.05 if cleanup_enabled else 0}
            elif cfg.checksums:
                weights={'clone':0.58,'checksums':0.10,'build':0.22,'verify':0.05 if cfg.verify_after else 0,'cleanup':0.05 if cleanup_enabled else 0}
            else:
                weights={'clone':0.60,'build':0.30,'verify':0.05 if cfg.verify_after else 0,'cleanup':0.05 if cleanup_enabled else 0}
        else:
            if cfg.prerender and cfg.checksums:
                weights={'clone':0.58,'prerender':0.22,'checksums':0.13,'verify':0.05 if cfg.verify_after else 0,'cleanup':0.04 if cleanup_enabled else 0}
            elif cfg.prerender:
                weights={'clone':0.70,'prerender':0.23,'verify':0.05 if cfg.verify_after else 0,'cleanup':0.02 if cleanup_enabled else 0}
            elif cfg.checksums:
                weights={'clone':0.75,'checksums':0.17,'verify':0.05 if cfg.verify_after else 0,'cleanup':0.03 if cleanup_enabled else 0}
            else:
                weights={'clone':0.92,'verify':0.05 if cfg.verify_after else 0,'cleanup':0.03 if cleanup_enabled else 0}
        weights={k:v for k,v in weights.items() if v>0}; total=sum(weights.values()) or 1
        for k in list(weights.keys()): weights[k]=weights[k]/total
        self._weighted=weights; self._phase_pct={k:0 for k in weights}; self._phase_start={}; self._phase_end={}
    def _update_weighted_progress(self,phase:str,pct:int):
        if phase not in self._weighted:
            self._weighted[phase]=0.02; tot=sum(self._weighted.values());
            for k in list(self._weighted.keys()): self._weighted[k]=self._weighted[k]/tot
        if phase not in self._phase_pct: self._phase_pct[phase]=0
        if pct>0 and phase not in self._phase_start: self._phase_start[phase]=time.time()
        self._phase_pct[phase]=pct
        if pct>=100 and phase not in self._phase_end: self._phase_end[phase]=time.time()
        tot=0.0
        for ph,w in self._weighted.items(): tot+=w*(self._phase_pct.get(ph,0)/100.0)
        overall=int(round(tot*100)); self.prog.setValue(overall); self.status_lbl.setText(f"{phase}: {pct}% (overall {overall}%)")

def launch():
    app=QApplication(sys.argv)
    # Set application-wide icon so macOS Dock / task switcher uses icon.png
    try:
        base=os.path.join(os.path.dirname(__file__),'images')
        tried=False
        ip=os.path.join(base,'icon.png')
        if os.path.exists(ip):
            app.setWindowIcon(QIcon(ip)); tried=True
        if not tried:
            root_dir=os.path.dirname(__file__)
            for ic in ('icon.icns','icon.ico','icon.png'):
                root_icon=os.path.join(root_dir,ic)
                if os.path.exists(root_icon):
                    app.setWindowIcon(QIcon(root_icon)); break
    except Exception:
        pass
    w=DockerClonerGUI(); w.resize(1000,760); w.show(); sys.exit(app.exec())

if __name__=='__main__':  # pragma: no cover
    launch()
