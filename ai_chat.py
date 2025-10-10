"""AI Chat Assistant integration (clean authoritative implementation).

Features:
  * Conversational Q&A (OpenRouter) with optional SSE streaming
  * Summarizes current config & recent log tail
  * Watch Mode: periodic background log analysis
  * Parses JSON change proposals (whitelist-enforced)
  * Risk heuristics & highlighting + owner risk callback
  * Diff preview + selective apply (owner supplies apply_ai_changes)
  * Transcript logging (opt-in; bearer redaction)
  * Owner optional callbacks:
        on_ai_proposed_changes(changes: dict)
        on_ai_changes_risk(changes: dict, risks: dict)

Notes:
  * Undo responsibility remains in the main GUI (external to this dialog)
  * Whitelist prevents the model from toggling unsafe / unrelated keys
"""
from __future__ import annotations

import os, json, time, threading, queue
from typing import Dict, Any, Optional
import httpx

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit, QPushButton, QCheckBox, QLabel, QComboBox,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QWidget
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor

OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"

# Curated list of models advertised as free / zero‑cost (subject to change on OpenRouter).
# Only these will be offered in the UI to avoid accidental cost incursion. Update manually as needed.
FREE_MODELS = [  # Static fallback seeds (used if live fetch fails)
    'meta-llama/llama-3-8b-instruct',
    'mistralai/mistral-7b-instruct',
    'google/gemma-2-9b-it',
    'qwen/qwen2-7b-instruct',
    'openchat/openchat-7b'
]

# Environment override is honored ONLY if inside FREE_MODELS; otherwise we fall back to first free model.
_env_model = os.getenv("OPENROUTER_MODEL", "").strip()
DEFAULT_MODEL = _env_model if _env_model in FREE_MODELS else FREE_MODELS[0]

WHITELIST = {
    'prerender','router_intercept','resilient','relaxed_tls','allow_degraded','incremental','capture_api','capture_storage',
    'capture_api_binary','capture_graphql','checksums','verify_after','verify_deep','disable_js','jobs','failure_threshold',
    'prerender_max_pages','prerender_scroll','auto_backoff','adaptive_concurrency','verbose_wget'
}

SYSTEM_PROMPT = (
    "You are an expert assistant for a website cloning + Docker packaging tool. "
    "Provide concise guidance. When recommending configuration changes, output a final JSON line: "
    "Changes: {\"changes\": {<field>: <value>, ...}} using only safe, whitelisted keys."
)

def parse_ai_changes(text: str) -> Optional[Dict[str,Any]]:
    if not text:
        return None
    for line in text.splitlines():
        if '"changes"' in line and '{' in line and '}' in line:
            try:
                s=line.index('{'); e=line.rfind('}')
                js=json.loads(line[s:e+1])
                if isinstance(js,dict) and isinstance(js.get('changes'),dict):
                    return {k:v for k,v in js['changes'].items() if k in WHITELIST}
            except Exception:
                continue
    return None

def assess_change_risks(current_cfg: Dict[str,Any], proposed: Dict[str,Any]) -> Dict[str,str]:
    risks: Dict[str,str] = {}
    try: cur_jobs=int(current_cfg.get('jobs') or 0)
    except Exception: cur_jobs=0
    nj=proposed.get('jobs')
    if isinstance(nj,(int,float)) and cur_jobs>0:
        try:
            if nj > cur_jobs*2 and nj >= 8:
                risks['jobs']=f'increase {cur_jobs}->{nj} (>2x)'
        except Exception: pass
    cur_ft=current_cfg.get('failure_threshold'); new_ft=proposed.get('failure_threshold')
    if isinstance(cur_ft,(int,float)) and isinstance(new_ft,(int,float)):
        if new_ft - cur_ft > 0.1 or new_ft > 0.35:
            risks['failure_threshold']=f'raised {cur_ft}->{new_ft}'
    if proposed.get('relaxed_tls') and not current_cfg.get('relaxed_tls'):
        risks['relaxed_tls']='relaxes TLS verification'
    if current_cfg.get('checksums') and proposed.get('checksums') is False:
        risks['checksums']='disables checksums'
    if current_cfg.get('verify_after') and proposed.get('verify_after') is False:
        risks['verify_after']='disables verification'
    return risks

def _summarize_config(cfg: Dict[str, Any]) -> str:
    parts=[]
    for k in sorted(cfg.keys()):
        v=cfg[k]
        if isinstance(v,str) and len(v)>80: v=v[:77]+"..."
        parts.append(f"{k}={v!r}")
        if len(parts)>=40:
            parts.append('… (truncated)'); break
    return '\n'.join(parts)

class ChatAssistantDialog(QDialog):
    def __init__(self, owner, get_config_callable, get_logs_callable, api_key_getter, parent=None):
        super().__init__(parent)
        self.setWindowTitle('AI Chat Assistant')
        self.resize(760,520)
        self._owner=owner
        self._get_config=get_config_callable
        self._get_logs=get_logs_callable
        self._api_key_getter=api_key_getter
        self._cooldown_until=0.0
        self._worker_q: queue.Queue = queue.Queue()
        self._stop=False
        self._streaming_enabled=True
        self._stream_buffer=''
        self._stream_lock=threading.Lock()
        self._transcript_path=None
        self._last_changes=None
        self._last_risks={}
        self._consec_stream_errors=0
        self._dynamic_free_models=[]
        self._dynamic_free_models_display=[]
        self._dynamic_free_models_map={}
        self._build_ui()
        self._start_background_poller()

    # ---------- UI ----------
    def _build_ui(self):
        lay=QVBoxLayout(self); lay.setContentsMargins(8,8,8,8); lay.setSpacing(6)
        top=QHBoxLayout(); top.setSpacing(8)
        self.model_box=QComboBox(); self.model_box.addItems([])
        # Ensure currently selected fallback is the validated DEFAULT_MODEL
        try:
            idx=self.model_box.findText(DEFAULT_MODEL)
            if idx>=0: self.model_box.setCurrentIndex(idx)
        except Exception:
            pass
        # Refresh models button (dynamic fetch of current free list)
        self.btn_refresh_models=QPushButton('Refresh Models')
        self.btn_refresh_models.setToolTip('Fetch current free models list from OpenRouter (filters zero-cost entries).')
        self.btn_refresh_models.clicked.connect(self._refresh_models_clicked)
        self.btn_diag=QPushButton('Show Model Diagnostics')
        self.btn_diag.setToolTip('Show current free model list and last response status.')
        self.btn_diag.clicked.connect(self._show_model_diag)
        self.chk_auto=QCheckBox('Watch Mode (periodic log analysis)')
        self.btn_analyze=QPushButton('Analyze Recent Logs'); self.btn_analyze.clicked.connect(self._analyze_logs)
        self.btn_verify_key=QPushButton('Verify API Key')
        self.btn_verify_key.setToolTip('Test your OpenRouter API key and show result.')
        self.btn_verify_key.clicked.connect(self._verify_api_key)
        top.addWidget(QLabel('Model:'))
        top.addWidget(self.model_box,1)
        top.addWidget(self.btn_refresh_models)
        top.addWidget(self.btn_verify_key)
        top.addWidget(self.btn_diag)
        top.addWidget(self.chk_auto)
        top.addWidget(self.btn_analyze)
        lay.addLayout(top)
        self.chat_view=QTextEdit(); self.chat_view.setReadOnly(True); lay.addWidget(self.chat_view,1)
        inrow=QHBoxLayout(); self.input=QLineEdit(); self.input.setPlaceholderText('Ask a question or: suggest dynamic settings')
        self.btn_send=QPushButton('Send'); self.btn_send.clicked.connect(self._send_user)
        inrow.addWidget(self.input,1); inrow.addWidget(self.btn_send); lay.addLayout(inrow)
        act=QHBoxLayout(); self.btn_apply=QPushButton('Apply Last Changes'); self.btn_apply.setEnabled(False); self.btn_apply.clicked.connect(self._apply_last)
        self.chk_stream=QCheckBox('Streaming'); self.chk_stream.setChecked(True); self.chk_stream.stateChanged.connect(lambda s: self._toggle_stream(bool(s)))
        self.chk_log=QCheckBox('Log Session')
        self.status_lbl=QLabel('Ready'); self.status_lbl.setStyleSheet('color:#888;')
        for w in (self.btn_apply,self.chk_stream,self.chk_log): act.addWidget(w)
        act.addStretch(1); act.addWidget(self.status_lbl); lay.addLayout(act)
        hint=QLabel('Responses may include a JSON Changes line; risk fields highlighted in amber.')
        hint.setStyleSheet('color:#aaa; font-size:11px;'); lay.addWidget(hint)
    def _verify_api_key(self):
        api_key = self._api_key_getter() or os.getenv('OPENROUTER_API_KEY')
        if not api_key:
            self._log('[error] No API key (set OPENROUTER_API_KEY env or fill AI API Key field).')
            return
        self._log('[system] Verifying OpenRouter API key...')
        def _do():
            try:
                headers = {'Authorization': f'Bearer {api_key}', 'HTTP-Referer': 'http://localhost/', 'X-Title': 'CW2DT Chat'}
                import httpx
                with httpx.Client(timeout=15) as client:
                    resp = client.get('https://openrouter.ai/api/v1/models', headers=headers)
                    if resp.status_code == 200:
                        self._log('[system] API key is valid!')
                    else:
                        self._log(f'[error] API key test failed: HTTP {resp.status_code} – {resp.text[:200]}')
            except Exception as e:
                self._log(f'[error] API key test exception: {e}')
        import threading
        threading.Thread(target=_do, daemon=True).start()
        lay.addLayout(top)
        self.chat_view=QTextEdit(); self.chat_view.setReadOnly(True); lay.addWidget(self.chat_view,1)
        inrow=QHBoxLayout(); self.input=QLineEdit(); self.input.setPlaceholderText('Ask a question or: suggest dynamic settings')
        self.btn_send=QPushButton('Send'); self.btn_send.clicked.connect(self._send_user)
        inrow.addWidget(self.input,1); inrow.addWidget(self.btn_send); lay.addLayout(inrow)
        act=QHBoxLayout(); self.btn_apply=QPushButton('Apply Last Changes'); self.btn_apply.setEnabled(False); self.btn_apply.clicked.connect(self._apply_last)
        self.chk_stream=QCheckBox('Streaming'); self.chk_stream.setChecked(True); self.chk_stream.stateChanged.connect(lambda s: self._toggle_stream(bool(s)))
        self.chk_log=QCheckBox('Log Session')
        self.status_lbl=QLabel('Ready'); self.status_lbl.setStyleSheet('color:#888;')
        for w in (self.btn_apply,self.chk_stream,self.chk_log): act.addWidget(w)
        act.addStretch(1); act.addWidget(self.status_lbl); lay.addLayout(act)
        hint=QLabel('Responses may include a JSON Changes line; risk fields highlighted in amber.')
        hint.setStyleSheet('color:#aaa; font-size:11px;'); lay.addWidget(hint)

    def _show_model_diag(self):
        diag = '[ai][diag] Current free models:\n' + '\n'.join(self._dynamic_free_models)
        if hasattr(self, '_last_model_status') and self._last_model_status:
            diag += '\nLast model status:\n' + self._last_model_status
        else:
            diag += '\nNo recent model status.'
        self._log(diag)

    # ---------- Helpers ----------
    def _set_status(self,msg:str):
        def _do():
            try: self.status_lbl.setText(msg)
            except Exception: pass
        QTimer.singleShot(0,_do)

    def _toggle_stream(self, enabled: bool):
        self._streaming_enabled=enabled
        self._set_status('Streaming ON' if enabled else 'Streaming OFF')

    # ---------- Model Refresh ----------
    def _refresh_models_clicked(self):
        self._set_status('Refreshing model list...')
        self._log('[ai] refreshing model list...')
        api_key=self._api_key_getter() or os.getenv('OPENROUTER_API_KEY')
        if not api_key:
            self._set_status('No API key for model refresh')
            self._log('[ai] cannot refresh models – no API key')
            return
        threading.Thread(target=self._refresh_free_models, args=(api_key,), daemon=True).start()

    def _refresh_free_models(self, api_key: str):
        """Fetch current models list, keep only zero-cost ones, update UI (best effort)."""
        try:
            headers={'Authorization':f'Bearer {api_key}','HTTP-Referer':'http://localhost/','X-Title':'CW2DT Chat'}
            with httpx.Client(timeout=30) as client:
                resp=client.get('https://openrouter.ai/api/v1/models', headers=headers)
            if resp.status_code!=200:
                self._log(f'[ai] model refresh failed HTTP {resp.status_code}')
                return
            js=resp.json()
            data=js.get('data') or []
            # Always show raw model data at the top of the chat view for diagnostics
            try:
                import pprint
                raw_data = pprint.pformat(data)
            except Exception as e:
                raw_data = str(data)
                print('[ai][error] pprint failed:', e)
            # Print to terminal for diagnostics
            print('[ai][diag] Raw model data from OpenRouter:\n' + raw_data[:8000])
            # Insert at the top of the chat view for visibility
            def _show_raw():
                try:
                    self.chat_view.insertPlainText('[ai][diag] Raw model data from OpenRouter:\n' + raw_data[:8000] + '\n')
                except Exception as e:
                    self._log('[ai][diag] Raw model data from OpenRouter:\n' + raw_data[:8000])
                    print('[ai][error] chat_view insert failed:', e)
            QTimer.singleShot(0, _show_raw)
            free=[]
            free_display=[]
            free_map={}
            for item in data:
                if not isinstance(item, dict):
                    continue
                mid = item.get('id') or item.get('name')
                name = item.get('name', mid)
                pricing = item.get('pricing') or {}
                try:
                    prompt_cost = float(str(pricing.get('prompt', '0')).strip())
                    comp_cost = float(str(pricing.get('completion', '0')).strip())
                except Exception:
                    prompt_cost = comp_cost = 0
                if mid and prompt_cost == 0 and comp_cost == 0:
                    free.append(mid)
                    disp = f"{name} ({mid})"
                    free_display.append(disp)
                    free_map[disp] = mid
            if not free:
                self._log('[ai] model refresh yielded no zero-cost entries; keeping existing list')
                return
            # Preserve currently selected if still present
            cur=self.model_box.currentText().strip()
            self._dynamic_free_models=free
            self._dynamic_free_models_display=free_display
            self._dynamic_free_models_map=free_map
            def _apply():
                print('[ai][debug] _apply called for dropdown update')
                print(f'[ai][debug] [pre-update] Dropdown list: {self._dynamic_free_models_display}')
                try:
                    self.model_box.blockSignals(True)
                    self.model_box.clear()
                    self.model_box.addItems(self._dynamic_free_models_display)
                    print(f'[ai][debug] [post-update] Dropdown count: {self.model_box.count()}')
                    if self._dynamic_free_models_display:
                        self.model_box.setCurrentIndex(0)
                        self._log(f'[ai] refreshed free models ({len(free)}): '+', '.join(self._dynamic_free_models_display[:6]) + (' …' if len(free)>6 else ''))
                    else:
                        self._log('[ai][error] No free models available. Dropdown is empty.')
                    self.model_box.blockSignals(False)
                except Exception as e:
                    print(f'[ai][error] Dropdown update failed: {e}')
                    self._log(f'[ai][error] Dropdown update failed: {e}')
            import threading
            print(f'[ai][debug] Directly calling _apply for dropdown update (thread: {threading.current_thread().name}, visible: {self.isVisible()})')
            _apply()
            self._set_status('Model list refreshed')
        except Exception as e:
            self._log(f'[ai] model refresh error: {e}')

    def _resolve_transcript_path(self):
        if self._transcript_path: return self._transcript_path
        try:
            cfg=self._get_config() or {}
            dest=cfg.get('dest') or cfg.get('output') or ''
            dname=cfg.get('docker_name') or 'site'
            if not dest: return None
            p=os.path.join(dest,dname,'.cw2dt'); os.makedirs(p,exist_ok=True)
            self._transcript_path=os.path.join(p,'ai_session.log'); return self._transcript_path
        except Exception:
            return None

    def _maybe_log_transcript(self,line:str):
        if not getattr(self,'chk_log',None) or not self.chk_log.isChecked(): return
        path=self._resolve_transcript_path()
        if not path: return
        try:
            red=line.replace('\n',' ').replace('\r',' ')
            if 'Bearer ' in red: red=red.split('Bearer ')[0]+'Bearer ****'
            with open(path,'a',encoding='utf-8') as f: f.write(red+'\n')
        except Exception: pass

    def closeEvent(self, ev):
        self._stop=True
        return super().closeEvent(ev)

    # ---------- Background Watch Mode ----------
    def _start_background_poller(self):
        def _loop():
            while not self._stop:
                try:
                    task=self._worker_q.get(timeout=0.35)
                    if task=='analyze': self._run_analysis(user_prompt=None, system_inject='(automatic log analysis)')
                except Exception: pass
        threading.Thread(target=_loop,daemon=True).start()
        self._timer=QTimer(self); self._timer.timeout.connect(self._maybe_schedule_auto); self._timer.start(4000)

    def _maybe_schedule_auto(self):
        if not self.chk_auto.isChecked(): return
        now=time.time()
        if now < self._cooldown_until: return
        self._cooldown_until= now + 25
        self._worker_q.put('analyze')

    # ---------- Interaction ----------
    def _log(self,text:str):
        print(f'[ai][debug] _log called with text: {text[:200]}')
        def _do():
            try:
                before = self.chat_view.toPlainText()
                self.chat_view.append(text)
                after = self.chat_view.toPlainText()
                self.chat_view.ensureCursorVisible()
                self._maybe_log_transcript(text)
                print(f'[ai][debug] chat_view after append, last 200 chars: {after[-200:]}')
                if after == before:
                    print('[ai][debug] append did not update chat_view, using setPlainText fallback')
                    new_content = before + ('\n' if before else '') + text
                    self.chat_view.setPlainText(new_content)
            except Exception as e:
                print(f'[ai][error] GUI log failed: {e}')
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, _do)

    def _send_user(self):
        p=self.input.text().strip()
        if not p: return
        self.input.clear(); self._log(f'You: {p}'); self._run_analysis(user_prompt=p)

    def _analyze_logs(self):
        self._log('[system] analyzing recent logs...'); self._run_analysis(user_prompt='Analyze recent logs and suggest minimal safe improvements.')

    def on_new_log(self,line:str):
        pass

    # ---------- Core flow ----------
    def _compose_context(self):
        cfg=self._get_config(); logs=self._get_logs();
        return cfg, f"Current Config (subset)\n{_summarize_config(cfg)}\n\nRecent Log Tail (last {min(120,len(logs))} lines)\n"+'\n'.join(logs[-120:])+'\n'

    def _run_analysis(self, user_prompt: Optional[str], system_inject: Optional[str]=None):
        cfg, ctx_text=self._compose_context()
        disp_model = self.model_box.currentText().strip() or (self._dynamic_free_models_display[0] if self._dynamic_free_models_display else DEFAULT_MODEL)
        model = self._dynamic_free_models_map.get(disp_model, self._dynamic_free_models[0] if self._dynamic_free_models else DEFAULT_MODEL)
        allowed = set(self._dynamic_free_models or FREE_MODELS)
        print(f'[ai][debug] Dropdown selected: "{disp_model}"')
        print(f'[ai][debug] Mapped model ID: "{model}"')
        if model not in allowed:
            # Hard guard: force back to first dynamic free model if out-of-band value slips in
            model = self._dynamic_free_models[0] if self._dynamic_free_models else DEFAULT_MODEL
            try: self._log('[system] model outside free allowlist; reverted to '+model)
            except Exception: pass
        api_key=self._api_key_getter() or os.getenv('OPENROUTER_API_KEY')
        if not api_key:
            self._log('[error] No API key (set OPENROUTER_API_KEY env or fill AI API Key field).'); return
        full=(system_inject+'\n' if system_inject else '') + (user_prompt or 'Provide a health assessment and improvements.') + '\n\nContext:\n'+ctx_text+'\nIf proposing config changes include final JSON line.'
        print(f'[ai][debug] Chat payload: model={model}, prompt={user_prompt}, system_inject={system_inject}')
        threading.Thread(target=self._exec_request, args=(api_key, model, full), daemon=True).start()

    def _exec_request(self, api_key: str, model: str, user_content: str):
        self._set_status('Querying...')
        print(f'[ai][debug] Sending request: model={model}, user_content={user_content[:100]}')
        if not self._streaming_enabled:
            try:
                payload={'model':model,'messages':[{'role':'system','content':SYSTEM_PROMPT},{'role':'user','content':user_content}], 'temperature':0.2,'max_tokens':600}
                headers={'Authorization':f'Bearer {api_key}','HTTP-Referer':'http://localhost/','X-Title':'CW2DT Chat'}
                with httpx.Client(timeout=45) as client:
                    resp=client.post(OPENROUTER_API,json=payload,headers=headers)
                    print(f'[ai][debug] Response status: {resp.status_code}')
                    print(f'[ai][debug] Response body: {resp.text[:400]}')
                    try:
                        resp.raise_for_status()
                    except Exception as e:
                        self._log(f'[ai][error] HTTP {resp.status_code}: {e}\nResponse body: {resp.text[:800]}')
                        self._process_response(f'[error] HTTP {resp.status_code}: {e}')
                        return
                    try:
                        data=resp.json()
                        print(f'[ai][debug] Parsed JSON: {json.dumps(data)[:400]}')
                    except Exception as e:
                        self._log(f'[ai][error] Failed to parse JSON: {e}\nRaw body: {resp.text[:800]}')
                        self._process_response(f'[error] Failed to parse JSON: {e}')
                        return
                content=data.get('choices',[{}])[0].get('message',{}).get('content','')
                print(f'[ai][debug] Extracted content: {content[:200]}')
                if not content:
                    self._log(f'[ai][error] No content in response. Full JSON: {json.dumps(data)[:800]}')
            except Exception as e:
                self._log(f'[ai][error] Exception: {e}')
                content=f'[error] {e}'
            self._process_response(content); return
        try:
            payload={'model':model,'messages':[{'role':'system','content':SYSTEM_PROMPT},{'role':'user','content':user_content}], 'temperature':0.2,'max_tokens':600,'stream':True}
            headers={'Authorization':f'Bearer {api_key}','HTTP-Referer':'http://localhost/','X-Title':'CW2DT Chat'}
            self._log('Assistant (streaming):')
            with httpx.Client(timeout=None) as client:
                with client.stream('POST',OPENROUTER_API,json=payload,headers=headers) as r:
                    status = getattr(r, 'status_code', None)
                    if status and status >=400:
                        try:
                            body = r.text if hasattr(r, 'text') else ''
                            self._log(f'[ai][error] Streaming HTTP {status}. Response body: {body[:800]}')
                        except Exception:
                            pass
                        # Special handling for 402 (Payment Required / quota) – rotate to next free model automatically.
                        if status == 402:
                            try: self._log(f'[ai] model {model} returned HTTP 402 (payment/quota) – attempting alternate free model...')
                            except Exception: pass
                            rotated=False
                            rotated = False
                            error_details = []
                            self._last_model_status = ''
                            for alt in self._dynamic_free_models:
                                if alt == model:
                                    continue
                                try:
                                    payload_alt = {'model': alt, 'messages': [{'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': user_content}], 'temperature': 0.2, 'max_tokens': 600, 'quota': 1}
                                    with httpx.Client(timeout=45) as c2:
                                        resp2 = c2.post(OPENROUTER_API, json=payload_alt, headers=headers)
                                        self._last_model_status += f'{alt}: HTTP {resp2.status_code}\n'
                                        if resp2.status_code == 200:
                                            try:
                                                data = resp2.json()
                                            except Exception as e:
                                                self._log(f'[ai][error] Failed to parse JSON for {alt}: {e}\nRaw body: {resp2.text[:800]}')
                                                error_details.append(f'{alt}: JSON parse error')
                                                self._last_model_status += f'{alt}: JSON parse error\n'
                                                continue
                                            content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
                                            if content:
                                                try:
                                                    self._log(f'[ai] switched to alternate free model: {alt}')
                                                except Exception:
                                                    pass
                                                self._last_model_status += f'{alt}: Success\n'
                                                self._process_response(content)
                                                rotated = True
                                                break
                                            else:
                                                self._log(f'[ai][error] No content from {alt}. Full JSON: {json.dumps(data)[:800]}')
                                                error_details.append(f'{alt}: No content')
                                                self._last_model_status += f'{alt}: No content\n'
                                        else:
                                            self._log(f'[ai][error] HTTP {resp2.status_code} for {alt}. Body: {resp2.text[:800]}')
                                            error_details.append(f'{alt}: HTTP {resp2.status_code}')
                                            self._last_model_status += f'{alt}: HTTP {resp2.status_code}\n'
                                except Exception as e:
                                    self._log(f'[ai][error] Exception for {alt}: {e}')
                                    error_details.append(f'{alt}: Exception {e}')
                                    self._last_model_status += f'{alt}: Exception {e}\n'
                            if not rotated:
                                self._log('[ai][error] No response received from any free model. Details: ' + '; '.join(error_details))
                                self._process_response('[error] No response received from any free model.\nDetails: ' + '; '.join(error_details))
                            return
                        else:
                            # 400/404 often indicate removed or invalid model id – rotate similar to 402 path
                            if status in (400,404):
                                try: self._log(f'[ai] streaming HTTP {status} for model {model}; trying alternate…')
                                except Exception: pass
                                rotated=False
                                for alt in (m for m in self._dynamic_free_models if m!=model):
                                    try:
                                        payload_alt={'model':alt,'messages':[{'role':'system','content':SYSTEM_PROMPT},{'role':'user','content':user_content}], 'temperature':0.2,'max_tokens':600}
                                        with httpx.Client(timeout=45) as c2:
                                            resp2=c2.post(OPENROUTER_API,json=payload_alt,headers=headers)
                                            if resp2.status_code==200:
                                                data=resp2.json(); content=data.get('choices',[{}])[0].get('message',{}).get('content','')
                                                if content:
                                                    self._log(f'[ai] switched to alternate (due to {status}): {alt}')
                                                    self._process_response(content)
                                                    rotated=True
                                                    break
                                    except Exception:
                                        continue
                                if not rotated:
                                    # Attempt non-stream fallback with original model to capture body error details
                                    try:
                                        with httpx.Client(timeout=45) as fcli:
                                            fresp=fcli.post(OPENROUTER_API,json={'model':model,'messages':[{'role':'system','content':SYSTEM_PROMPT},{'role':'user','content':user_content}],'temperature':0.2,'max_tokens':600},headers=headers)
                                            detail=fresp.text[:800]
                                            self._log(f'[ai][error] Non-stream fallback HTTP {fresp.status_code}. Body: {detail}')
                                            self._process_response(f'[error] streaming HTTP {status} (detail: {detail})')
                                    except Exception as e:
                                        self._log(f'[ai][error] Exception in non-stream fallback: {e}')
                                        self._process_response(f'[error] streaming HTTP {status}')
                                return
                            self._process_response(f'[error] streaming HTTP {status}')
                            return
                    for raw in r.iter_lines():
                        if not raw: continue
                        if not raw.startswith('data:'): continue
                        seg=raw[5:].strip()
                        if not seg:
                            continue
                        if seg=='[DONE]':
                            break
                        try:
                            js=json.loads(seg)
                        except Exception:
                            # Non-JSON keep-alive / comment line
                            continue
                        # Try multiple extraction paths (delta.content, message.content)
                        choice = (js.get('choices') or [{}])[0]
                        delta_txt = None
                        if isinstance(choice, dict):
                            delta_txt = choice.get('delta',{}).get('content') or choice.get('message',{}).get('content')
                        if delta_txt:
                            with self._stream_lock:
                                self._stream_buffer += delta_txt
                            def _upd(d=delta_txt):
                                try:
                                    from PySide6.QtGui import QTextCursor; self.chat_view.moveCursor(QTextCursor.MoveOperation.End)
                                except Exception: pass
                                self.chat_view.insertPlainText(d); self.chat_view.ensureCursorVisible(); self._set_status('Streaming...')
                            QTimer.singleShot(0,_upd)
                        else:
                            # No token text; show raw chunk for diagnostics
                            raw_chunk = json.dumps(js)
                            def _upd_raw():
                                try:
                                    from PySide6.QtGui import QTextCursor; self.chat_view.moveCursor(QTextCursor.MoveOperation.End)
                                except Exception: pass
                                self.chat_view.insertPlainText('[ai][stream][raw] ' + raw_chunk + '\n'); self.chat_view.ensureCursorVisible(); self._set_status('Streaming...')
                            QTimer.singleShot(0, _upd_raw)
            final=self._stream_buffer; self._stream_buffer=''
            if not final:
                # Fallback: re-run non-stream request to salvage a reply
                try:
                    self._set_status('Fallback (non-stream)')
                    payload_ns={'model':model,'messages':[{'role':'system','content':SYSTEM_PROMPT},{'role':'user','content':user_content}], 'temperature':0.2,'max_tokens':600}
                    with httpx.Client(timeout=45) as client:
                        resp=client.post(OPENROUTER_API,json=payload_ns,headers=headers)
                        data=resp.json()
                        final=data.get('choices',[{}])[0].get('message',{}).get('content','[error] Empty streaming + empty fallback')
                except Exception as e:
                    final=f'[error] Empty streaming response (fallback failed: {e})'
            self._process_response(final)
        except Exception as e:
            self._process_response(f'[error] streaming failed: {e}')
            self._consec_stream_errors+=1
            if self._consec_stream_errors>=3 and self._streaming_enabled:
                # Auto-disable streaming after repeated failures
                self._streaming_enabled=False
                try: self._log('[ai] auto-disabled streaming after repeated failures')
                except Exception: pass
        else:
            # Reset error counter on success path
            self._consec_stream_errors=0

    def _process_response(self, text: str):
        print(f'[ai][debug] Processing response: {text[:400]}')
        def _do():
            changes=parse_ai_changes(text)
            if changes:
                self._last_changes=changes; self.btn_apply.setEnabled(True)
            self._log(f'Assistant: {text}')
            try:
                from PySide6.QtGui import QTextCursor
                self.chat_view.moveCursor(QTextCursor.MoveOperation.End)
                self.chat_view.ensureCursorVisible()
            except Exception as e:
                print(f'[ai][error] chat_view scroll failed: {e}')
            if changes:
                self._log(f'[assistant] Parsed changes: {changes}')
                try:
                    cfg=self._get_config(); risks=assess_change_risks(cfg, changes); self._last_risks=risks
                    if risks:
                        self._log('[risk] '+', '.join(f"{k}: {v}" for k,v in risks.items()))
                        if hasattr(self._owner,'on_ai_changes_risk'):
                            try: self._owner.on_ai_changes_risk(changes, risks)
                            except Exception: pass
                except Exception: pass
                try:
                    if hasattr(self._owner,'on_ai_proposed_changes'): self._owner.on_ai_proposed_changes(changes)
                except Exception: pass
            self._set_status('Done')
        QTimer.singleShot(0, _do)

    def _apply_last(self):
        if not self._last_changes: return
        dlg=DiffPreviewDialog(self._get_config(), self._last_changes, parent=self)
        if dlg.exec()==QDialog.DialogCode.Accepted:
            sel=dlg.selected_changes()
            if not sel: self._log('[system] no fields selected'); return
            applied=self._owner.apply_ai_changes(sel)
            if applied:
                self._log('[system] applied: '+', '.join(applied)); self.btn_apply.setEnabled(False); self._last_changes=None
            else:
                self._log('[system] no changes applied (all filtered)')

class DiffPreviewDialog(QDialog):
    def __init__(self, current_cfg: Dict[str,Any], proposed: Dict[str,Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle('AI Proposed Changes')
        self.resize(560,360)
        self._proposed=proposed
        self._current=current_cfg
        self._accepted=set(proposed.keys())
        lay=QVBoxLayout(self); lay.setContentsMargins(8,8,8,8); lay.setSpacing(6)
        self.tbl=QTableWidget(0,4,self); self.tbl.setHorizontalHeaderLabels(['Field','Current','Proposed','Accept'])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.tbl,1)
        risks=assess_change_risks(current_cfg, proposed)
        for k,v in proposed.items():
            r=self.tbl.rowCount(); self.tbl.insertRow(r); cur=current_cfg.get(k)
            self.tbl.setItem(r,0,QTableWidgetItem(k))
            cur_it=QTableWidgetItem(repr(cur)); prop_it=QTableWidgetItem(repr(v))
            if k in risks:
                col=QColor(255,210,120); cur_it.setBackground(col); prop_it.setBackground(col)
                tip=f'Risk: {risks[k]}'; cur_it.setToolTip(tip); prop_it.setToolTip(tip)
            self.tbl.setItem(r,1,cur_it); self.tbl.setItem(r,2,prop_it)
            from PySide6.QtWidgets import QCheckBox as _CB
            cb=_CB(); cb.setChecked(True)
            def _wrap(field):
                def _toggle(state):
                    if state==Qt.CheckState.Checked: self._accepted.add(field)
                    else: self._accepted.discard(field)
                return _toggle
            cb.stateChanged.connect(_wrap(k))
            container=QWidget(); hl=QHBoxLayout(container); hl.setContentsMargins(0,0,0,0); hl.addWidget(cb); hl.addStretch(1)
            self.tbl.setCellWidget(r,3,container)
        btns=QHBoxLayout(); b_all=QPushButton('All'); b_none=QPushButton('None'); b_apply=QPushButton('Apply'); b_cancel=QPushButton('Cancel')
        b_all.clicked.connect(lambda: self._set_all(True)); b_none.clicked.connect(lambda: self._set_all(False))
        b_apply.clicked.connect(self.accept); b_cancel.clicked.connect(self.reject)
        for b in (b_all,b_none): btns.addWidget(b)
        btns.addStretch(1); btns.addWidget(b_apply); btns.addWidget(b_cancel); lay.addLayout(btns)

    def _set_all(self,val:bool):
        self._accepted=set(self._proposed.keys()) if val else set()
        for r in range(self.tbl.rowCount()):
            cont=self.tbl.cellWidget(r,3)
            if not cont: continue
            from PySide6.QtWidgets import QCheckBox as _CB_CLASS
            for child in cont.children():
                if isinstance(child,_CB_CLASS):
                    try: child.blockSignals(True); child.setChecked(val); child.blockSignals(False)
                    except Exception: pass

    def selected_changes(self)->Dict[str,Any]:
        return {k:self._proposed[k] for k in self._accepted if k in self._proposed}

__all__=['ChatAssistantDialog','WHITELIST','parse_ai_changes','DiffPreviewDialog','assess_change_risks']
