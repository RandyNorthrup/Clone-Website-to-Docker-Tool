"""Lightweight AI adapter service for Auto Retry AI Assist.

This service exposes a single POST endpoint /cw2dt-ai that accepts the
payload produced by the GUI's Auto Retry Supervisor and returns a
JSON object of safe configuration changes under {"changes": {...}}.

It translates the internal tool payload into an OpenRouter chat
completion request, enforces a strict whitelist of adjustable fields,
adds guardrails on numeric ranges, and emits a minimal response.

Usage:
  1. Install dependencies (fastapi, uvicorn, httpx) if not already.
  2. Export your OpenRouter key: export OPENROUTER_API_KEY=sk-or-XXXX
  3. Run: python ai_adapter.py
  4. In the GUI Automation / AI Assist section set the endpoint to:
       http://127.0.0.1:5005/cw2dt-ai

Security:
  - The OpenRouter API key is ONLY read from environment; never embed it in code.
  - Sensitive fields (auth passwords, cookies) are stripped before sending to the model.
  - If the key is missing or any upstream error occurs we degrade to empty changes {}.

Response Contract:
  Always returns a JSON object: {"changes": {<field>: <value>, ...}}
  Empty dict means no changes recommended.
"""
from __future__ import annotations

import os, json, re, math
from typing import Dict, Any
from fastapi import FastAPI
from pydantic import BaseModel
import httpx

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
MAX_FIELD_CHANGES = 4
REQUEST_TIMEOUT = float(os.getenv("AI_ADAPTER_TIMEOUT", "25"))
CACHE_TTL = float(os.getenv("AI_ADAPTER_CACHE_TTL", "90"))  # seconds

ADJUSTABLE_SANITY = {
    "jobs": (2, 128),
    "prerender_max_pages": (1, 2000),
    "prerender_scroll": (0, 50),
    # failure_threshold is a float 0..1
}

SENSITIVE_KEYS = {"auth_user", "auth_pass", "cookies_file"}

SYSTEM_PROMPT = """You are a STRICT configuration tuner.\nReturn ONLY a raw JSON object of field:value pairs (or an empty JSON object {}).\nRules:\n- Only mutate fields listed in adjustable_fields.\n- Prefer <=4 small, conservative changes.\n- Avoid drastic changes (do not set jobs < 2).\n- If no improvement expected, return {}.\n- Do not include explanations, markdown, code fences, or extra wrapping.\n"""

class CW2DTPayload(BaseModel):
    attempt: int
    max_attempts: int
    base_config: Dict[str, Any]
    current_config: Dict[str, Any]
    recent_logs: list
    adjustable_fields: list

app = FastAPI(title="CW2DT AI Adapter", version="1.1")

# In-memory simple cache: key -> (expires_ts, response_dict)
_CACHE: dict[str, tuple[float, dict]] = {}

def _summarize_logs(lines, cap_chars=1600):
    if not lines:
        return ""
    tail = lines[-120:]
    joined = "\n".join(tail)
    if len(joined) <= cap_chars:
        return joined
    return joined[-cap_chars:]

def _diff(base: Dict[str, Any], cur: Dict[str, Any]):
    parts=[]
    for k,v in cur.items():
        if k in base and base[k] != v:
            parts.append(f"{k}:{base[k]!r}->{v!r}")
            if len(parts) >= 30:
                break
    return ", ".join(parts)

def _redact(config: Dict[str, Any]):
    clean = {}
    for k,v in config.items():
        if k in SENSITIVE_KEYS:
            continue
        clean[k] = v
    return clean

@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL, "cache_items": len(_CACHE)}

def _cache_key(payload: CW2DTPayload) -> str:
    # Key off attempt number + a hash of current_config + last few error lines to avoid overgrowth
    import hashlib, json as _json
    tail = "\n".join(payload.recent_logs[-30:])
    basis = {
        "attempt": payload.attempt,
        "max_attempts": payload.max_attempts,
        "current_config": payload.current_config,
        "recent_tail": tail,
        "adjustable": payload.adjustable_fields,
    }
    blob = _json.dumps(basis, sort_keys=True).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()

def _cache_get(key: str):
    import time
    ent = _CACHE.get(key)
    if not ent: return None
    exp, value = ent
    if time.time() > exp:
        _CACHE.pop(key, None)
        return None
    return value

def _cache_set(key: str, value: dict):
    import time
    _CACHE[key] = (time.time() + CACHE_TTL, value)

@app.post("/cw2dt-ai")
async def cw2dt_ai(payload: CW2DTPayload):
    # Fail-safe if no key or no model: return empty changes
    if not OPENROUTER_API_KEY:
        return {"changes": {}}

    adjustable = set(payload.adjustable_fields)

    # Cache check (skip for first attempt to encourage fresh look)
    ckey = None
    if payload.attempt > 1:
        ckey = _cache_key(payload)
        cached = _cache_get(ckey)
        if cached:
            return cached
    base_clean = _redact(payload.base_config)
    cur_clean = _redact(payload.current_config)

    user_prompt = f"""Attempt {payload.attempt}/{payload.max_attempts}\nAdjustable: {sorted(list(adjustable))}\nCurrent vs Base Diff: {_diff(base_clean, cur_clean) or 'none'}\nRecent Logs (tail trimmed):\n{_summarize_logs(payload.recent_logs)}\nReturn only a JSON object of changed fields.\n"""

    request_body = {
        "model": MODEL,
        "messages": [
            {"role":"system","content": SYSTEM_PROMPT},
            {"role":"user","content": user_prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 180
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "http://localhost/",
        "X-Title": "CW2DT AI Assist"
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post("https://openrouter.ai/api/v1/chat/completions", json=request_body, headers=headers)
        data = resp.json()
    except Exception:
        result = {"changes": {}}
        if ckey: _cache_set(ckey, result)
        return result

    # Drill into model content
    try:
        content = data["choices"][0]["message"]["content"]
    except Exception:
        result = {"changes": {}}
        if ckey: _cache_set(ckey, result)
        return result

    # Extract first {...} JSON object
    m = re.search(r"{.*}", content, re.DOTALL)
    if not m:
        result = {"changes": {}}
        if ckey: _cache_set(ckey, result)
        return result
    raw_json = m.group(0)
    try:
        js = json.loads(raw_json)
    except Exception:
        result = {"changes": {}}
        if ckey: _cache_set(ckey, result)
        return result

    # Accept {changes:{...}} or direct dict
    if isinstance(js, dict) and "changes" in js and isinstance(js["changes"], dict):
        js = js["changes"]

    if not isinstance(js, dict):
        result = {"changes": {}}
        if ckey: _cache_set(ckey, result)
        return result

    filtered = {}
    for k,v in js.items():
        if k not in adjustable:
            continue
        if len(filtered) >= MAX_FIELD_CHANGES:
            break
        # Type + sanity checks
        if k == "jobs":
            try:
                iv = int(v)
                lo,hi = ADJUSTABLE_SANITY["jobs"]
                if iv < lo or iv > hi: continue
                filtered[k] = iv
            except Exception:
                continue
        elif k in ("prerender_max_pages","prerender_scroll"):
            try:
                iv = int(v)
                lo,hi = ADJUSTABLE_SANITY[k]
                if iv < lo or iv > hi: continue
                filtered[k] = iv
            except Exception:
                continue
        elif k == "failure_threshold":
            try:
                fv = float(v)
                if fv < 0.0 or fv > 1.0: continue
                # avoid absurd tiny changes (round to 3 decimals)
                filtered[k] = round(fv,3)
            except Exception:
                continue
        else:
            # Allow simple bool/int/float/str
            if isinstance(v,(bool,int,float,str)):
                filtered[k] = v
    response = {"changes": filtered, "explanation": "cached heuristic JSON-only tuning" if filtered else "no change"}
    if ckey: _cache_set(ckey, response)
    return response

if __name__ == "__main__":  # pragma: no cover
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5005)
