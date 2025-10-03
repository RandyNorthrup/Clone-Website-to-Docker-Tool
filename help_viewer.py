"""Help / Documentation viewer for Clone Website to Docker Tool.

Provides a simple dialog with two tabs:
 - Contents: hierarchical tree of topics (grouped by category)
 - Index/Search: flat searchable list

Topics are loaded from an embedded JSON structure (can be later externalized to help_topics.json).
Each topic: id, title, category, body (markdown). Markdown rendered with minimal formatting to HTML.
"""
from __future__ import annotations

import json, textwrap, re, os
from dataclasses import dataclass
from typing import List, Dict
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem, QListWidget, QListWidgetItem as QListItem,
    QTextBrowser, QLineEdit, QLabel, QTabWidget, QWidget, QPushButton, QSizePolicy, QMessageBox
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QShortcut, QKeySequence

@dataclass
class HelpTopic:
    id: str
    title: str
    category: str
    body: str

TOPICS_PATH = os.path.join(os.path.dirname(__file__), 'help_topics.json')

# Minimal embedded fallback knowledge base (used if external file missing)
_RAW_TOPICS = [
    {
        "id":"intro","title":"Introduction","category":"Getting Started","body": textwrap.dedent("""
        # Clone Website to Docker Tool
        This tool captures a website (static + optional dynamic rendering) and packages the result into a Docker image.

        Workflow:
        1. Enter the site URL & destination.
        2. (Optional) Enable prerender for dynamic/SPAs.
        3. Choose build/run/serve options.
        4. Click Clone.

        Use Profiles (File menu) to save / load common configurations.
        """)
    },
    {
        "id":"prerender","title":"Prerender (Dynamic Rendering)","category":"Dynamic Capture","body": textwrap.dedent("""
        ## Prerender (Playwright)
        When enabled, pages are loaded in a headless Chromium browser to allow JavaScript execution, client-side routing, and data fetching.

        Recommendations:
        - Enable for SPAs / JS heavy sites (React, Vue, Next.js, etc.).
        - Combine with Router Interception to enumerate navigation-based routes.
        - Scroll Passes help trigger lazy loading and infinite scroll.
        - DOM Stability waits for network/DOM quiet period before snapshotting.
        """)
    },
    {
        "id":"router","title":"Router Intercept","category":"Dynamic Capture","body": textwrap.dedent("""
        ## Router Interception
        Captures client-side navigations (pushState / history API) to discover additional routes in SPAs.

        Options:
        - Include hash fragment: treat #anchor changes as separate routes.
        - Allow / Deny: regex filters (comma separated) applied to discovered routes.
        - Wait Selector: CSS selector to wait for before snapshot per route.
        """)
    },
    {
        "id":"integrity","title":"Checksums & Verify","category":"Integrity","body": textwrap.dedent("""
        ## Integrity & Verification
        Computing checksums allows later detection of drift/change. After clone you can verify output matches recorded hashes.
        Enable Diff or Incremental to optimize subsequent runs and produce change summaries.
        """)
    },
    {
        "id":"resilience","title":"Resilience & Quality","category":"Reliability","body": textwrap.dedent("""
        ## Resilience & Quality
        These options increase tolerance to flaky networks and classify run quality.
        - Resilient: Broader retries/timeouts during initial pass.
        - Relaxed TLS: Disables keep-alive/caching and forces insecure TLS (diagnostic / last resort).
        - Failure Threshold: Error ratio (0-1) above which a quality re-attempt or degraded flag may trigger.
        - Allow Degraded: Treat run as success even if ratio exceeded (logs quality event).
        """)
    },
    {
        "id":"wizard","title":"Wizard Recommendations","category":"Guidance","body": textwrap.dedent("""
        ## Wizard
        Scans the root page for frameworks, script density, JSON data hints, and GraphQL/API markers to propose feature enablement:
        - Prerender & Router Intercept for SPAs.
        - API / Storage capture when dynamic data patterns detected.
        - Checksums & Incremental for heavy dynamic content.
        Accept the suggestions or manually adjust before cloning.
        """)
    },
]

def _load_topics() -> List[HelpTopic]:
    # Try external JSON file first
    try:
        if os.path.exists(TOPICS_PATH):
            with open(TOPICS_PATH,'r',encoding='utf-8') as f:
                data=json.load(f)
            if isinstance(data, list):
                return [HelpTopic(**t) for t in data if isinstance(t, dict) and {'id','title','category','body'} <= set(t.keys())]
    except Exception:
        pass
    # Fallback
    return [HelpTopic(**t) for t in _RAW_TOPICS]

_TOPICS: List[HelpTopic] = _load_topics()

def _validate_internal_links():
    pattern = re.compile(r"\[\[([a-z0-9_]+)\]\]|\(help:([a-z0-9_]+)\)")
    ids = {t.id for t in _TOPICS}
    missing = set()
    for t in _TOPICS:
        for m in pattern.finditer(t.body):
            tid = m.group(1) or m.group(2)
            if tid not in ids:
                missing.add((t.id, tid))
    if missing:
        print("[help] Missing cross-link targets:")
        for src, tgt in sorted(missing):
            print(f"  {src} -> {tgt}")

_validate_internal_links()

class HelpViewer(QDialog):
    """Modal help viewer with:
    - Back/Forward history (Alt+Left / Alt+Right)
    - Optional initial topic
    - Command extraction + copy (Ctrl+Shift+C or button)
    """
    def __init__(self, parent=None, show_index: bool=False, initial_topic: str | None = None):
        super().__init__(parent)
        self.setWindowTitle('Help')
        self.resize(860, 580)
        lay=QVBoxLayout(self)
        # History state
        self._history: List[str] = []
        self._hist_index: int = -1
        self._suppress_history = False
        self._current_search_term: str | None = None
        self._current_commands: List[str] = []
        self._current_topic: str | None = None

        # Navigation / actions bar
        nav_bar = QHBoxLayout(); nav_bar.setSpacing(6)
        from PySide6.QtWidgets import QToolButton
        self.back_btn = QToolButton(); self.back_btn.setText('⟨ Back'); self.back_btn.clicked.connect(self._go_back); self.back_btn.setEnabled(False)
        self.forward_btn = QToolButton(); self.forward_btn.setText('Forward ⟩'); self.forward_btn.clicked.connect(self._go_forward); self.forward_btn.setEnabled(False)
        self.home_btn = QToolButton(); self.home_btn.setText('Home'); self.home_btn.clicked.connect(lambda: self._navigate('intro'))
        self.copy_btn = QToolButton(); self.copy_btn.setText('Copy Commands'); self.copy_btn.setToolTip('Copy install / shell commands referenced in this topic (Ctrl+Shift+C).'); self.copy_btn.clicked.connect(self._copy_commands); self.copy_btn.setEnabled(False)
        self.status_lbl = QLabel('')
        self.status_lbl.setStyleSheet('color:#888; font-size:11px;')
        nav_bar.addWidget(self.back_btn); nav_bar.addWidget(self.forward_btn); nav_bar.addWidget(self.home_btn); nav_bar.addWidget(self.copy_btn); nav_bar.addStretch(1); nav_bar.addWidget(self.status_lbl,0, Qt.AlignmentFlag.AlignRight)
        lay.addLayout(nav_bar)

        self.tabs=QTabWidget(); lay.addWidget(self.tabs,1)
        self._build_contents_tab()
        self._build_index_tab()
        if show_index:
            self.tabs.setCurrentIndex(1)
        # Footer close button
        btn_row=QHBoxLayout(); btn_row.addStretch(1)
        close_btn=QPushButton('Close'); close_btn.clicked.connect(self.accept); btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)
        # Keyboard shortcuts (store refs to avoid GC)
        self._sc_back = QShortcut(QKeySequence('Alt+Left'), self); self._sc_back.activated.connect(self._go_back)
        self._sc_fwd = QShortcut(QKeySequence('Alt+Right'), self); self._sc_fwd.activated.connect(self._go_forward)
        self._sc_copy = QShortcut(QKeySequence('Ctrl+Shift+C'), self); self._sc_copy.activated.connect(self._copy_commands)
        self._sc_close = QShortcut(QKeySequence('Escape'), self); self._sc_close.activated.connect(self.accept)
        self._sc_reload = QShortcut(QKeySequence('F5'), self); self._sc_reload.activated.connect(lambda: (self._current_topic and self._show_topic(self._current_topic)))
        # Initial topic / default
        self._navigate(initial_topic or 'intro')

    # ----- Contents Tab -----
    def _build_contents_tab(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(6,6,6,6); v.setSpacing(6)
        self.tree=QTreeWidget(); self.tree.setHeaderHidden(True)
        cats: Dict[str, QTreeWidgetItem] = {}
        for topic in _TOPICS:
            if topic.category not in cats:
                cats[topic.category]=QTreeWidgetItem([topic.category])
                self.tree.addTopLevelItem(cats[topic.category])
            item=QTreeWidgetItem([topic.title]); item.setData(0, Qt.ItemDataRole.UserRole, topic.id)
            cats[topic.category].addChild(item)
        self.tree.expandAll()
        self.viewer=QTextBrowser()
        # We'll intercept help:// links for internal cross-topic navigation
        self.viewer.setOpenExternalLinks(False)
        self.viewer.anchorClicked.connect(self._on_anchor_clicked)
        splitter_layout=QHBoxLayout(); splitter_layout.addWidget(self.tree,1); splitter_layout.addWidget(self.viewer,3)
        v.addLayout(splitter_layout,1)
        self.tree.currentItemChanged.connect(lambda cur,prev: self._on_tree(cur))
        self.tabs.addTab(w,'Contents')

    # ----- Index / Search Tab -----
    def _build_index_tab(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(6,6,6,6); v.setSpacing(6)
        self.search_in=QLineEdit(); self.search_in.setPlaceholderText('Search topics...'); v.addWidget(self.search_in)
        self.list=QListWidget(); v.addWidget(self.list,1)
        for t in _TOPICS:
            item=QListItem(t.title); item.setData(Qt.ItemDataRole.UserRole, t.id); self.list.addItem(item)
        self.list.currentItemChanged.connect(lambda cur,prev: self._on_list(cur))
        self.search_in.textChanged.connect(self._filter_list)
        self.tabs.addTab(w,'Index')

    def _filter_list(self, text: str):
        text=text.strip().lower()
        for i in range(self.list.count()):
            item=self.list.item(i)
            tid=item.data(Qt.ItemDataRole.UserRole)
            topic=next((t for t in _TOPICS if t.id==tid), None)
            visible=True
            if text:
                hay=f"{topic.title}\n{topic.body}".lower() if topic else ''
                visible=text in hay
            item.setHidden(not visible)

    def _show_topic(self, topic_id: str):
        topic=next((t for t in _TOPICS if t.id==topic_id), None)
        if not topic:
            return
        # naive markdown-ish to HTML with internal cross-link expansion
        body=topic.body
        self._current_topic = topic_id
        # Extract candidate commands BEFORE we mutate markup
        self._current_commands = self._extract_commands(body)
        self.copy_btn.setEnabled(bool(self._current_commands))
        # Replace [[topic_id]] with anchor link to help://topic_id
        id_map = {t.id: t.title for t in _TOPICS}
        def _sub_link(m):
            tid=m.group(1)
            title=id_map.get(tid, tid)
            return f"<a href='help://{tid}' style='color:#6cf; text-decoration:none;'>{title}</a>"
        body=re.sub(r'\[\[([a-z0-9_]+)\]\]', _sub_link, body)
        # Allow markdown style [text](help:topic_id)
        def _sub_md(m):
            text, tid = m.group(1), m.group(2)
            if tid in id_map:
                return f"<a href='help://{tid}' style='color:#6cf; text-decoration:none;'>{text}</a>"
            return m.group(0)
        body=re.sub(r'\[([^\]]+)\]\(help:([a-z0-9_]+)\)', _sub_md, body)
        body=re.sub(r'^### (.+)$', r'<h3>\1</h3>', body, flags=re.MULTILINE)
        body=re.sub(r'^## (.+)$', r'<h2>\1</h2>', body, flags=re.MULTILINE)
        body=re.sub(r'^# (.+)$', r'<h1>\1</h1>', body, flags=re.MULTILINE)
        body=re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', body)
        body=re.sub(r'\*(.+?)\*', r'<i>\1</i>', body)
        body=body.replace('\n\n', '<br><br>')
        # Simple search term highlight (case-insensitive) on raw body (post-markup conversion)
        if self._current_search_term:
            term = self._current_search_term.strip()
            if len(term) >= 3:
                pattern = re.compile(re.escape(term), re.IGNORECASE)
                body = pattern.sub(lambda m: f"<span style='background:#444; color:#fff;'>{m.group(0)}</span>", body)
        html=f"<html><body style='font-family:Sans-Serif; font-size:13px; color:#ddd; background:#222;'>" \
             f"<h1 style='font-size:19px;'>{topic.title}</h1>{body}</body></html>"
        self.viewer.setHtml(html)
        self._select_in_tree(topic_id)
        self._update_nav_buttons()
        # Clear transient status label (do not persist old copy state)
        self.status_lbl.setText('')

    # ---- Command Extraction / Copy ----
    def _extract_commands(self, raw: str) -> List[str]:
        """Heuristically extract install / shell commands from backticked or fenced code fragments.
        Matches typical package manager & tool patterns to avoid copying prose.
        """
        patterns_prefix = (
            'pip install', 'pip3 install', 'playwright install', 'brew install', 'brew update',
            'sudo apt-get', 'sudo apt', 'sudo dnf', 'sudo yum', 'sudo pacman', 'sudo zypper', 'sudo apk',
            'winget install', 'choco install', 'curl -fsSL', 'docker run', 'python -m venv', 'python3 -m venv'
        )
        cmds=set()
        # Inline backticks
        for m in re.finditer(r'`([^`]+)`', raw):
            sn=m.group(1).strip()
            low=sn.lower()
            if any(low.startswith(p) for p in patterns_prefix):
                cmds.add(sn)
        # Lines starting with typical tokens
        for line in raw.splitlines():
            ln=line.strip()
            low=ln.lower()
            if any(low.startswith(p) for p in patterns_prefix):
                cmds.add(ln)
        # Maintain original appearance order
        ordered=[]
        for line in raw.splitlines():
            if line.strip() in cmds and line.strip() not in ordered:
                ordered.append(line.strip())
        return ordered

    def _copy_commands(self):
        if not self._current_commands:
            self.status_lbl.setText('No commands detected')
            return
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText('\n'.join(self._current_commands))
            self.status_lbl.setText(f"Copied {len(self._current_commands)} cmd(s)")
        except Exception as e:
            QMessageBox.warning(self,'Copy Failed', str(e))

    def _on_tree(self, cur):
        if not cur: return
        tid=cur.data(0, Qt.ItemDataRole.UserRole)
        if tid: self._navigate(tid)

    def _on_list(self, cur):
        if not cur: return
        tid=cur.data(Qt.ItemDataRole.UserRole)
        if tid:
            # capture current search term for highlighting
            self._current_search_term = self.search_in.text().strip() or None
            self._navigate(tid)
        # Sync tree selection to the matching topic
        # (optional future enhancement)

    def _on_anchor_clicked(self, url: QUrl):
        if url.scheme() == 'help':
            self._navigate(url.host() or url.path().lstrip('/'))
        else:
            # For external links, open in default browser
            import webbrowser
            webbrowser.open(url.toString())

    # ----- Navigation helpers -----
    def _navigate(self, topic_id: str):
        if self._suppress_history:
            self._show_topic(topic_id)
            return
        # If navigating from middle of history, truncate forward part
        if self._hist_index < len(self._history) - 1:
            self._history = self._history[:self._hist_index+1]
        self._history.append(topic_id)
        self._hist_index += 1
        self._show_topic(topic_id)

    def _go_back(self):
        if self._hist_index > 0:
            self._hist_index -= 1
            self._suppress_history = True
            self._show_topic(self._history[self._hist_index])
            self._suppress_history = False
            self._update_nav_buttons()

    def _go_forward(self):
        if self._hist_index < len(self._history) - 1:
            self._hist_index += 1
            self._suppress_history = True
            self._show_topic(self._history[self._hist_index])
            self._suppress_history = False
            self._update_nav_buttons()

    def _update_nav_buttons(self):
        self.back_btn.setEnabled(self._hist_index > 0)
        self.forward_btn.setEnabled(self._hist_index < len(self._history) - 1)

    def _select_in_tree(self, topic_id: str):
        # Iterate categories and children to find item
        root = self.tree
        for i in range(root.topLevelItemCount()):
            cat = root.topLevelItem(i)
            if not cat:
                continue
            for j in range(cat.childCount()):
                child = cat.child(j)
                if child and child.data(0, Qt.ItemDataRole.UserRole) == topic_id:
                    self.tree.setCurrentItem(child)
                    return

if __name__=='__main__':  # manual test
    from PySide6.QtWidgets import QApplication
    import sys
    app=QApplication(sys.argv)
    dlg=HelpViewer(); dlg.show(); sys.exit(app.exec())
