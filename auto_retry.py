"""Automated multi-attempt clone supervisor with heuristic + optional AI adjustments.

The AutoRetryManager wraps a single call to clone_site() allowing:
  * Multiple attempts (max_attempts) until success
  * Safe heuristic adjustments between attempts (resilient mode, reduced jobs, retry args)
  * Optional AI assist: POST current config + context to an HTTP endpoint which
    returns JSON containing a whitelist of config field mutations.

Design goals:
  * Keep adjustments conservative to preserve 1:1 fidelity (avoid destructive toggles)
  * Remain side-effect free with respect to original CloneConfig (work on a copy)
  * Provide transparent log lines so the GUI console shows exactly what changed
  * Fail fast on AI errors – never block or prevent further attempts if endpoint fails
"""
from __future__ import annotations

from dataclasses import asdict, replace
from typing import Optional, Dict, Any, List
import json, urllib.request, urllib.error, time, copy

from cw2dt_core import clone_site, CloneConfig, CloneResult, CloneCallbacks

# Whitelist of fields the AI (or heuristics) may modify safely.
ADJUSTABLE_FIELDS = {
    'jobs','resilient','relaxed_tls','failure_threshold','allow_degraded',
    'prerender','router_intercept','incremental','capture_api','capture_storage',
    'capture_api_binary','capture_graphql','checksums','verify_after','verify_deep',
    'prerender_max_pages','prerender_scroll'
}

class _BufferingCallbacks(CloneCallbacks):
    """Wrap underlying callbacks to capture recent log lines for AI context while forwarding."""
    def __init__(self, inner: CloneCallbacks, max_lines: int = 120):
        self._inner = inner
        self._lines: List[str] = []
        self._max = max_lines
    # Passthroughs
    def phase(self, phase: str, pct: int):
        if hasattr(self._inner,'phase'): self._inner.phase(phase,pct)
    def bandwidth(self, rate: str):
        if hasattr(self._inner,'bandwidth'): self._inner.bandwidth(rate)
    def api_capture(self, count: int):
        if hasattr(self._inner,'api_capture'): self._inner.api_capture(count)
    def router_count(self, count: int):
        if hasattr(self._inner,'router_count'): self._inner.router_count(count)
    def checksum(self, pct: int):
        if hasattr(self._inner,'checksum'): self._inner.checksum(pct)
    def is_canceled(self)->bool:
        if hasattr(self._inner,'is_canceled'): return self._inner.is_canceled()
        return False
    def log(self, message: str):
        self._lines.append(message)
        if len(self._lines)>self._max:
            self._lines=self._lines[-self._max:]
        if hasattr(self._inner,'log'): self._inner.log(message)
    def tail(self)->List[str]:
        return list(self._lines)

class AutoRetryManager:
    # Hint attribute for static analyzers
    event_sink: Optional[Any]
    def __init__(self, base_config: CloneConfig, max_attempts: int = 3,
                 ai_assist: bool = False, ai_endpoint: Optional[str] = None,
                 ai_api_key: Optional[str] = None):
        self.base = copy.deepcopy(base_config)
        self.max_attempts = max(1, max_attempts)
        self.ai_assist = ai_assist and bool(ai_endpoint)
        self.ai_endpoint = ai_endpoint.strip() if ai_endpoint else None
        self.ai_api_key = ai_api_key.strip() if ai_api_key else None
        self.attempts: List[Dict[str, Any]] = []  # metadata per attempt
    # Optional structured event sink callable accepting a dict.
    self.event_sink = None  # type: ignore

    # ---------------- Heuristic Adjustments -----------------
    def _heuristic_adjust(self, cfg: CloneConfig, attempt_index: int, last_result: Optional[CloneResult], cb: CloneCallbacks) -> CloneConfig:
        mutated = False
        notes = []
        # 1. First failure: enable resilient if not already
        if not cfg.resilient:
            cfg = replace(cfg, resilient=True)
            mutated = True; notes.append('enable resilient')
        # 2. Reduce jobs (threads) gradually (never below 2) if still failing
        if attempt_index>=1 and cfg.jobs>6:
            new_jobs = max(4, cfg.jobs // 2)
            if new_jobs != cfg.jobs:
                cfg = replace(cfg, jobs=new_jobs)
                mutated = True; notes.append(f'reduce jobs->{new_jobs}')
        # 3. Add retry/backoff args if not present yet
        extra = cfg.extra_wget_args or ''
        if '--retry-on-http-error' not in extra:
            addition = '--retry-on-http-error=429,500,503 --tries=3 --waitretry=2'
            extra = (extra + ' ' + addition).strip()
            cfg = replace(cfg, extra_wget_args=extra)
            mutated = True; notes.append('add retry args')
        if mutated:
            cb.log('[auto] heuristic adjustments: ' + ', '.join(notes))
            self._emit({'event':'auto_retry_heuristic','attempt':attempt_index+1,'notes':notes})
        else:
            cb.log('[auto] no heuristic adjustments applicable')
        return cfg

    # ---------------- AI Assist -----------------
    def _call_ai(self, cfg: CloneConfig, attempt_index: int, buffered_cb: _BufferingCallbacks, cb: CloneCallbacks) -> CloneConfig:
        if not self.ai_assist or not self.ai_endpoint:
            return cfg
        payload = {
            'attempt': attempt_index+1,
            'max_attempts': self.max_attempts,
            'base_config': asdict(self.base),
            'current_config': asdict(cfg),
            'recent_logs': buffered_cb.tail(),
            'adjustable_fields': sorted(list(ADJUSTABLE_FIELDS))
        }
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(self.ai_endpoint, data=data, method='POST', headers={'Content-Type': 'application/json'})
        if self.ai_api_key:
            req.add_header('Authorization', f'Bearer {self.ai_api_key}')
        try:
            with urllib.request.urlopen(req, timeout=18) as resp:
                raw = resp.read(100_000).decode('utf-8','ignore')
            try:
                js = json.loads(raw)
            except Exception:
                cb.log('[auto][ai] invalid JSON response – ignoring')
                return cfg
            if not isinstance(js, dict):
                cb.log('[auto][ai] response not an object – ignoring')
                return cfg
            changes = js.get('changes') or js  # allow direct dict
            if not isinstance(changes, dict):
                cb.log('[auto][ai] changes missing or not an object – ignoring')
                return cfg
            applied = []
            new_cfg = cfg
            for k,v in changes.items():
                if k in ADJUSTABLE_FIELDS and hasattr(new_cfg, k):
                    try:
                        new_cfg = replace(new_cfg, **{k: v})
                        applied.append(f'{k}={v!r}')
                    except Exception:
                        continue
            if applied:
                cb.log('[auto][ai] applied: ' + ', '.join(applied))
                self._emit({'event':'auto_retry_ai_applied','attempt':attempt_index+1,'changes':{k:v for k,v in changes.items() if k in ADJUSTABLE_FIELDS}})
                return new_cfg
            cb.log('[auto][ai] no valid changes proposed')
            return new_cfg
        except urllib.error.URLError as e:
            cb.log(f'[auto][ai] request failed: {e}')
        except Exception as e:
            cb.log(f'[auto][ai] unexpected error: {e}')
        return cfg

    # ---------------- Run Loop -----------------
    def run(self, cb: CloneCallbacks) -> CloneResult:
        buffered_cb = _BufferingCallbacks(cb)
        last_result: Optional[CloneResult] = None
        current_cfg = copy.deepcopy(self.base)
        for attempt in range(self.max_attempts):
            buffered_cb.log(f'[auto] attempt {attempt+1}/{self.max_attempts} starting')
            self._emit({'event':'auto_retry_attempt_start','attempt':attempt+1,'max_attempts':self.max_attempts,'config_snapshot':asdict(current_cfg)})
            result = clone_site(current_cfg, buffered_cb)
            self.attempts.append({'attempt': attempt+1, 'success': bool(getattr(result,'success',False)), 'config_snapshot': asdict(current_cfg)})
            if result and getattr(result,'success',False):
                buffered_cb.log(f'[auto] attempt {attempt+1} succeeded')
                self._emit({'event':'auto_retry_attempt_end','attempt':attempt+1,'success':True})
                self._emit({'event':'auto_retry_complete','attempts':self.attempts})
                return result
            buffered_cb.log(f'[auto] attempt {attempt+1} failed')
            self._emit({'event':'auto_retry_attempt_end','attempt':attempt+1,'success':False})
            last_result = result
            if attempt == self.max_attempts-1:
                break  # exhausted attempts
            # Adjust configuration for next attempt
            current_cfg = self._heuristic_adjust(current_cfg, attempt, last_result, buffered_cb)
            current_cfg = self._call_ai(current_cfg, attempt, buffered_cb, buffered_cb)
            # Small backoff to avoid immediate hammering
            time.sleep(1.2)
        # All attempts failed – return last result (or fabricate minimal failure)
        self._emit({'event':'auto_retry_complete','attempts':self.attempts})
        if last_result is not None:
            return last_result
        # Fabricate a failure result if clone_site returned None every time (unlikely)
        try:
            return CloneResult(False, False, self.base.dest, self.base.dest)
        except Exception:
            class _Fallback: success=False; docker_built=False; output_folder=self.base.dest; site_root=self.base.dest
            return _Fallback()  # type: ignore

    # -------------- Structured Event Emitter --------------
    def _emit(self, payload: Dict[str,Any]):
        if not self.event_sink:
            return
        try:
            self.event_sink(payload)
        except Exception:
            pass

__all__ = ['AutoRetryManager','ADJUSTABLE_FIELDS']
