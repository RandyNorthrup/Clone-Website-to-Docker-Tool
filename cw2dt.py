"""GUI + Headless tool for cloning websites into a Docker‑servable static snapshot.

Provides:
    * wget2-driven mirroring with optional pre-render (Playwright) & SPA route interception
    * Checksum manifest generation and post-clone verification utilities
    * Optional Docker image build + run helpers (nginx static server)
    * Resume support with existing/partial file counting
    * Live validation, recent destinations/URLs persistence, contextual help dialogs
    * Headless CLI mode for automation / CI (omit PySide6 import path)

All long-running work executes in a worker thread emitting granular progress
signals which are merged into a single animated progress bar in the GUI.
"""
import sys, os, subprocess, shutil, platform, socket, webbrowser, ipaddress, importlib, time
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

# Qt imports are deferred until after headless handling to allow running without PySide6 installed.

# ---------- helpers ----------
PARTIAL_SUFFIXES = {".tmp", ".part", ".partial", ".download"}

# Environment flag to allow importing helper functions without bringing in Qt (used by tests)
CW2DT_NO_QT = bool(os.environ.get('CW2DT_NO_QT'))

# ---- default configuration constants (centralize scattered magic numbers) ----
DEFAULT_PRERENDER_MAX_PAGES = 40
DEFAULT_ROUTER_MAX_ROUTES = 200
DEFAULT_ROUTER_SETTLE_MS = 350  # ms
DEFAULT_CONTAINER_PORT = 80
DEFAULT_HOST_PORT = 8080

# ---- style constants (centralize repeated inline styles) ----
VERIFY_BADGE_STYLE_OK = "color:#0a750a;font-weight:600;"
VERIFY_BADGE_STYLE_FAIL = "color:#b00000;font-weight:600;"

# ---- lightweight internal self-test samples ----
_VERIFICATION_SAMPLE_OUTPUT = """Some lines\nOK=120 Missing=0 Mismatched=0 Total=120\nDone"""

def _selftest_verification_parsing():  # dev aid, invoked via --selftest-verification
    sample = _VERIFICATION_SAMPLE_OUTPUT
    print("[selftest] sample input:\n" + sample)
    stats = parse_verification_summary(sample)
    print(f"[selftest] parsed: {stats}")
    assert stats == {'ok':120,'missing':0,'mismatched':0,'total':120}, "parse_verification_summary failed selftest"
    print("[selftest] SUCCESS")

 # NOTE: Transitional marker retained briefly during refactor; safe to remove when stable.

# ---- verification helpers (shared GUI + headless) ----
_VERIFICATION_RE = None
def parse_verification_summary(text: str):
    """Parse verification stdout summary lines into a dict.
    Pattern: OK=\\d+ Missing=\\d+ Mismatched=\\d+ Total=\\d+
    Cached regex compiled on first use to avoid recompilation in repeated calls.
    """
    if not text:
        return {'ok':None,'missing':None,'mismatched':None,'total':None}
    global _VERIFICATION_RE
    if _VERIFICATION_RE is None:
        import re as _re
        _VERIFICATION_RE = _re.compile(r"OK=(\d+) Missing=(\d+) Mismatched=(\d+) Total=(\d+)")
    for line in text.splitlines():
        m = _VERIFICATION_RE.search(line)
        if m:
            ok, missing, mismatched, total = map(int, m.groups())
            return {'ok':ok,'missing':missing,'mismatched':mismatched,'total':total}
    return {'ok':None,'missing':None,'mismatched':None,'total':None}

# ---- pure validation helper (GUI-independent; used in tests) ----
def validate_required_fields(url: str, dest: str, ip_text: str, build_docker: bool, docker_name: str) -> list[str]:
    """Return a list of human-readable validation errors for required core fields.
    Keeps GUI validation testable in headless mode.
    """
    errs: list[str] = []
    if not (url or '').strip():
        errs.append('Website URL required')
    if not (dest or '').strip():
        errs.append('Destination Folder required')
    if not (ip_text or '').strip():
        errs.append('Bind IP invalid')
    if build_docker and not (docker_name or '').strip():
        errs.append('Docker image name required when building')
    return errs

def run_verification(manifest_path: str, fast: bool=True, docker_name: str|None=None, project_dir: str|None=None, readme: bool=True, output_cb=None):
    """Invoke verification script and enrich manifest/README.
    Returns: (passed: bool, stats: dict)
    """
    import json, subprocess as _sp, sys as _sys, os as _os
    if not manifest_path or not _os.path.exists(manifest_path):
        return False, {'ok':None,'missing':None,'mismatched':None,'total':None}
    script = _os.path.join(_os.path.dirname(__file__), 'verify_checksums.py')
    cmd=[_sys.executable, script, '--manifest', manifest_path]
    if fast:
        cmd.append('--fast-missing')
    try:
        res=_sp.run(cmd,capture_output=True,text=True)
    except Exception as e:
        if output_cb: output_cb(f"[verify] error launching verifier: {e}")
        return False, {'ok':None,'missing':None,'mismatched':None,'total':None}
    stdout = res.stdout or ''
    if stdout and output_cb:
        for line in stdout.splitlines():
            output_cb(line)
    stats = parse_verification_summary(stdout)
    passed = (res.returncode == 0)
    # Single read/update/write cycle
    try:
        with open(manifest_path,'r',encoding='utf-8') as mf:
            data=json.load(mf)
        data['verification']={
            'status':'passed' if passed else 'failed',
            'ok':stats['ok'],'missing':stats['missing'],'mismatched':stats['mismatched'],'total':stats['total'],
            'fast_missing':fast
        }
        with open(manifest_path,'w',encoding='utf-8') as mf:
            json.dump(data,mf,indent=2)
    except Exception:
        pass
    if readme and docker_name and project_dir:
        try:
            rd=_os.path.join(project_dir,f"README_{docker_name}.md")
            if _os.path.exists(rd):
                with open(rd,'a',encoding='utf-8') as rf:
                    rf.write("\n### Verification Result\n")
                    if passed and stats['ok'] is not None and stats['total'] is not None:
                        rf.write(f"Passed ({stats['ok']}/{stats['total']} files)\n")
                    elif passed:
                        rf.write("Passed\n")
                    else:
                        rf.write(f"Failed (ok={stats['ok']} missing={stats['missing']} mismatched={stats['mismatched']} total={stats['total']})\n")
        except Exception:
            pass
    return passed, stats

# ---- checksum helper (shared headless + GUI thread) ----
def compute_checksums(base_folder: str, extra_extensions: list[str] | None = None, progress_cb=None, chunk_size: int = 65536):
    """Compute SHA256 checksums for HTML/HTM, API JSON under _api/, and optional extra extensions.
    Returns mapping {relative_path: sha256hex}.
    progress_cb (optional) called as progress_cb(processed, total) for coarse progress.
    """
    import hashlib, os as _os, time as _t
    extra_ext = [e.lower().lstrip('.') for e in (extra_extensions or []) if e]
    extra_ext_tuple = tuple(f".{e}" if not e.startswith('.') else e for e in extra_ext)
    candidates = []
    norm_api = '/_api/'
    start_time = _t.time()
    for root, _, files in _os.walk(base_folder):
        norm_root = root.replace('\\','/')
        is_api_dir = (norm_api in (norm_root + '/'))  # cheap contains check
        for fn in files:
            low = fn.lower()
            cond_html = low.endswith(('.html', '.htm'))
            cond_api = is_api_dir and low.endswith('.json')
            cond_extra = extra_ext_tuple and low.endswith(extra_ext_tuple)
            if cond_html or cond_api or cond_extra:
                candidates.append((root, fn))
    total = len(candidates)
    checks = {}
    last_emit = 0.0
    for idx, (root, fn) in enumerate(candidates, 1):
        p = _os.path.join(root, fn)
        rel = _os.path.relpath(p, base_folder)
        try:
            h = hashlib.sha256()
            with open(p, 'rb') as cf:
                for chunk in iter(lambda: cf.read(chunk_size), b''):
                    h.update(chunk)
            checks[rel] = h.hexdigest()
        except Exception:
            continue
        if progress_cb:
            now = _t.time()
            if idx == 1 or idx == total or (idx % 50 == 0) or (now - last_emit) > 0.6:
                last_emit = now
                try:
                    progress_cb(idx, total)
                except Exception:
                    pass
    return checks

# Reintroduce basic helpers (some code below references these)
def is_wget2_available():
    try:
        subprocess.run(["wget2","--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False

def count_files_and_partials(base_path: str):
    total=0; partials=0
    if not base_path or not os.path.isdir(base_path):
        return 0,0
    for root, _, files in os.walk(base_path):
        for f in files:
            total +=1
            lf=f.lower()
            for suf in PARTIAL_SUFFIXES:
                if lf.endswith(suf):
                    partials +=1; break
    return total, partials

def get_install_cmd(program: str):
    mgrs_linux=["apt-get","apt","dnf","yum","pacman","zypper","apk"]
    os_name=platform.system()
    if os_name=="Darwin":
        if shutil.which("brew"):
            if program=="wget2": return ["brew","install","wget2"]
            if program=="docker": return ["brew","install","--cask","docker"]
        return None
    if os_name=="Linux":
        for mgr in mgrs_linux:
            if not shutil.which(mgr): continue
            if program=="wget2":
                if mgr in ("apt-get","apt"): return ["sudo",mgr,"install","-y","wget2"]
                if mgr in ("dnf","yum"): return ["sudo",mgr,"install","-y","wget2"]
                if mgr=="pacman": return ["sudo","pacman","-S","--noconfirm","wget2"]
                if mgr=="zypper": return ["sudo","zypper","install","-y","wget2"]
                if mgr=="apk": return ["sudo","apk","add","wget2"]
            if program=="docker":
                if mgr in ("apt-get","apt"): return ["sudo",mgr,"install","-y","docker.io"]
                if mgr in ("dnf","yum"): return ["sudo",mgr,"install","-y","docker"]
                if mgr=="pacman": return ["sudo","pacman","-S","--noconfirm","docker"]
                if mgr=="zypper": return ["sudo","zypper","install","-y","docker"]
                if mgr=="apk": return ["sudo","apk","add","docker"]
        return None
    if os_name=="Windows":
        if program=="wget2":
            return None
        if shutil.which("winget") and program=="docker":
            return ["winget","install","-e","--id","Docker.DockerDesktop"]
        if shutil.which("choco") and program=="docker":
            return ["choco","install","docker-desktop","-y"]
        return None
    return None

def docker_available():
    try:
        subprocess.run(["docker", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False

def docker_install_instructions():
    os_name = platform.system()
    if os_name == "Windows":
        return "winget install Docker.DockerDesktop"
    if os_name == "Darwin":
        return "brew install --cask docker"
    if os_name == "Linux":
        return "sudo apt-get update && sudo apt-get install -y docker.io  # Debian/Ubuntu\nsudo yum install -y docker  # Fedora/RHEL"
    return "Please install Docker manually for your platform."

def normalize_ip(ip_text: str) -> str:
    ip_text = (ip_text or "").strip()
    if ip_text == "":
        return "127.0.0.1"
    if ip_text.lower() == "localhost":
        return "127.0.0.1"
    if ip_text == "0.0.0.0":
        return "0.0.0.0"
    try:
        ipaddress.IPv4Address(ip_text)
        return ip_text
    except Exception:
        return ""  # invalid

def get_primary_lan_ip(default="127.0.0.1"):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return default

def port_in_use(ip: str, port: int) -> bool:
    target_ip = "127.0.0.1" if ip == "0.0.0.0" else ip
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        try:
            return s.connect_ex((target_ip, port)) == 0
        except Exception:
            return False

def find_site_root(base_path):
    for root, _, files in os.walk(base_path):
        if any(f.lower() in ("index.html", "index.htm", "index.php") for f in files):
            return root
    return base_path

def human_quota_suffix(bytes_val):
    if bytes_val >= 1024**3: return f"{bytes_val // (1024**3)}G"
    if bytes_val >= 1024**2: return f"{bytes_val // (1024**2)}M"
    if bytes_val >= 1024:    return f"{bytes_val // 1024}K"
    return str(bytes_val)

def human_rate_suffix(bytes_per_sec):
    if bytes_per_sec >= 1024**2: return f"{bytes_per_sec // (1024**2)}M"
    if bytes_per_sec >= 1024:    return f"{bytes_per_sec // 1024}K"
    return str(bytes_per_sec)

def parse_size_to_bytes(text: str) -> int | None:
    if not text:
        return None
    t = text.strip().upper()
    try:
        if t.endswith('TB'):
            return int(float(t[:-2]) * (1024**4))
        if t.endswith('GB'):
            return int(float(t[:-2]) * (1024**3))
        if t.endswith('MB'):
            return int(float(t[:-2]) * (1024**2))
        if t.endswith('KB'):
            return int(float(t[:-2]) * 1024)
        if t.endswith('T'):
            return int(float(t[:-1]) * (1024**4))
        if t.endswith('G'):
            return int(float(t[:-1]) * (1024**3))
        if t.endswith('M'):
            return int(float(t[:-1]) * (1024**2))
        if t.endswith('K'):
            return int(float(t[:-1]) * 1024)
        return int(float(t))
    except Exception:
        return None

def parse_rate_to_bps(text: str) -> int | None:
    # Accept e.g., 500K, 2M (bytes/sec like wget2 expects)
    return parse_size_to_bytes(text)

# ---------- enhanced compatibility (optional prerender) ----------
def _run_prerender(start_url: str, site_root: str, output_folder: str, max_pages: int = 40,
                   capture_api: bool = False, hook_script: str | None = None,
                   rewrite_urls: bool = True, progress_cb=None, progress_percent_cb=None,
                   api_capture_cb=None,
                   router_intercept: bool = False, router_include_hash: bool = False,
                   router_max_routes: int = 200, router_settle_ms: int = 350,
                   router_wait_selector: str | None = None,
                   router_allow: list[str] | None = None,
                   router_deny: list[str] | None = None,
                   router_route_cb=None,
                   router_quiet: bool = False):
    """Use Playwright (if installed) to prerender dynamic pages and optionally capture API responses.
    - Saves rendered HTML into existing mirrored files if present, or creates them if missing.
    - Captures JSON/XHR responses into _api/ folder preserving path structure.
    - Optional user hook script can mutate the page before HTML extraction.
    This function is best-effort and silently returns if Playwright is not available.
    """
    def emit(msg):
        if progress_cb:
            try: progress_cb(msg)
            except Exception: pass
        else:
            print(f"[prerender] {msg}")
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        emit("Playwright not installed; skipping prerender.")
        return
    hook_fn = None
    if hook_script and os.path.exists(hook_script):
        try:
            import runpy
            mod = runpy.run_path(hook_script)
            hook_fn = mod.get('on_page')
            if hook_fn:
                emit("Loaded hook on_page()")
        except Exception as e:
            emit(f"Hook load failed: {e}")
    visited = set()
    to_visit = [start_url]
    router_seen = set()
    api_dir = os.path.join(output_folder, '_api') if capture_api else None
    if api_dir:
        os.makedirs(api_dir, exist_ok=True)
    from urllib.parse import urlparse, urljoin
    origin = None
    try:
        origin_parts = urlparse(start_url)
        origin = f"{origin_parts.scheme}://{origin_parts.netloc}"
    except Exception:
        origin = None
    import re
    allow_res = [re.compile(pat) for pat in (router_allow or [])]
    deny_res = [re.compile(pat) for pat in (router_deny or [])]
    def _route_allowed(norm: str) -> bool:
        try:
            if allow_res and not any(r.search(norm) for r in allow_res):
                return False
            if deny_res and any(r.search(norm) for r in deny_res):
                return False
            return True
        except Exception:
            return False
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        captured = []
        if capture_api:
            def on_response(resp):
                try:
                    ct = resp.headers.get('content-type','')
                    if 'application/json' in ct:
                        urlp = urlparse(resp.url)
                        path = urlp.path or '/'
                        if path.endswith('/'):
                            path += 'index.json'
                        if not path.endswith('.json'):
                            path += '.json'
                        if api_dir:
                            dest_path = os.path.join(api_dir, path.lstrip('/'))
                        else:
                            dest_path = os.path.join(output_folder, '_api_fallback', path.lstrip('/'))
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        data = resp.text()
                        with open(dest_path,'w',encoding='utf-8') as f: f.write(data)
                        captured.append(path)
                        if api_capture_cb:
                            try:
                                api_capture_cb(len(captured))
                            except Exception:
                                pass
                except Exception:
                    pass
            context.on('response', on_response)
        pages_processed = 0
        while to_visit and pages_processed < max_pages:
            url = to_visit.pop(0)
            if url in visited:
                continue
            visited.add(url)
            try:
                page = context.new_page()
                page.goto(url, wait_until='networkidle')
                # If router interception enabled, expose binding and inject patch script
                if router_intercept:
                    try:
                        def _enqueue_route(source, route_path):  # type: ignore
                            try:
                                if not isinstance(route_path, str):
                                    return
                                # Normalize route path; allow full URLs
                                from urllib.parse import urlparse
                                rp = route_path
                                up = urlparse(rp if (rp.startswith('http://') or rp.startswith('https://')) else (origin + rp if origin else rp))
                                if origin and up.netloc and (up.scheme + '://' + up.netloc) != origin:
                                    return  # skip cross-origin
                                norm = up.path or '/'
                                if up.query:
                                    norm = norm + '?' + up.query
                                if router_include_hash and up.fragment:
                                    norm = norm + '#' + up.fragment
                                full = (origin + norm) if origin else norm
                                if (full not in visited and full not in to_visit and full not in router_seen
                                        and len(router_seen) < max(1, router_max_routes)
                                        and len(visited) + len(to_visit) < max_pages):
                                    if _route_allowed(norm):
                                        router_seen.add(full)
                                        to_visit.append(full)
                                        if not router_quiet:
                                            emit(f"Router discovered: {norm}")
                                        if router_route_cb:
                                            try:
                                                router_route_cb(len(router_seen))
                                            except Exception:
                                                pass
                            except Exception:
                                pass
                        page.expose_binding("__cw2dt_enqueue_route", _enqueue_route)
                        # Inject interception patch
                        interception_js = f"""
                            (()=>{{
                              if (window.__cw2dt_router_patched__) return; window.__cw2dt_router_patched__=true;
                              const enqueue = (u)=>{{ try{{ window.__cw2dt_enqueue_route(u); }}catch(e){{}} }};
                              const norm = (u)=>{{ try{{ const x=new URL(u, location.href); return x.pathname + (x.search||'') + {( 'x.hash' if router_include_hash else "''" )}; }}catch(e){{ return u; }} }};
                              const origPush = history.pushState; history.pushState = function(s,t,u){{ origPush.apply(this, arguments); if(u) enqueue(norm(u)); }};
                              const origRep = history.replaceState; history.replaceState = function(s,t,u){{ origRep.apply(this, arguments); if(u) enqueue(norm(u)); }};
                              window.addEventListener('popstate', ()=>enqueue(norm(location.href)) );
                              window.addEventListener('hashchange', ()=>enqueue(norm(location.href)) );
                              document.addEventListener('click', (e)=>{{
                                const a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
                                if(!a) return; const href=a.getAttribute('href'); if(!href) return;
                                if(href.startsWith('mailto:')||href.startsWith('javascript:')) return;
                                enqueue(norm(href));
                              }}, {{capture:true}});
                            }})();
                        """
                        page.add_init_script(interception_js)
                    except Exception:
                        pass
                if hook_fn:
                    try:
                        hook_fn(page, url, context)
                    except Exception as e:
                        emit(f"Hook error on {url}: {e}")
                # Allow router-settle period before snapshot (captures immediate client redirects)
                if router_intercept and router_settle_ms > 0:
                    try:
                        page.wait_for_timeout(router_settle_ms)
                    except Exception:
                        pass
                if router_intercept and router_wait_selector:
                    try:
                        page.wait_for_selector(router_wait_selector, timeout=router_settle_ms * 2)
                    except Exception:
                        pass
                html = page.content()
                if rewrite_urls and origin:
                    html = html.replace(origin, '')
                # Determine output path relative to site_root
                rel = 'index.html'
                try:
                    up = urlparse(url)
                    rel = up.path
                    if rel.endswith('/') or rel == '':
                        rel = (rel.rstrip('/') + '/index.html') if rel else 'index.html'
                    if not rel.endswith('.html'):
                        # Only overwrite existing mirror HTML, else skip to avoid polluting non-html assets
                        if not rel.split('/')[-1].count('.'):  # no extension
                            rel = rel.rstrip('/') + '.html'
                except Exception:
                    pass
                out_path = os.path.join(site_root, rel.lstrip('/'))
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path,'w',encoding='utf-8') as f:
                    f.write(html)
                pages_processed += 1
                if progress_percent_cb:
                    try:
                        pct = int((pages_processed / max_pages) * 100)
                        progress_percent_cb(pct)
                    except Exception:
                        pass
                emit(f"Prerendered {url} → {rel}")
                # Discover links
                for a in page.query_selector_all('a[href]'):
                    try:
                        href = a.get_attribute('href')
                        if not href: continue
                        if href.startswith('mailto:') or href.startswith('javascript:'): continue
                        new_url = urljoin(url, href)
                        if origin and not new_url.startswith(origin):
                            continue
                        if new_url not in visited and new_url not in to_visit:
                            to_visit.append(new_url)
                    except Exception:
                        continue
                page.close()
            except Exception as e:
                emit(f"Failed prerender {url}: {e}")
        browser.close()
        if capture_api:
            emit(f"Captured {len(captured)} JSON responses.")
    emit(f"Prerender finished. Pages: {pages_processed}, Remaining queue: {len(to_visit)}")
    if progress_percent_cb:
        try: progress_percent_cb(100)
        except Exception: pass

# ---------- headless CLI ----------
def headless_main(argv: list[str]) -> int:
    import argparse, subprocess
    parser = argparse.ArgumentParser(description="Clone website to a Docker-ready folder (headless mode)")
    parser.add_argument('--headless', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--url', required=True, help='Website URL to mirror')
    parser.add_argument('--dest', required=True, help='Destination base folder')
    parser.add_argument('--docker-name', default='site', help='Docker image name / project folder name')
    parser.add_argument('--build', action='store_true', help='Build Docker image after clone')
    parser.add_argument('--bind-ip', default='127.0.0.1', help='Host bind IP (e.g., 127.0.0.1 or 0.0.0.0)')
    parser.add_argument('--host-port', type=int, default=8080, help='Host port to map')
    parser.add_argument('--container-port', type=int, default=80, help='Container port to expose')
    parser.add_argument('--size-cap', default=None, help='Optional download quota (e.g., 500M, 2G)')
    parser.add_argument('--throttle', default=None, help='Optional download limit (e.g., 500K, 4M)')
    parser.add_argument('--auth-user', default=None)
    parser.add_argument('--auth-pass', default=None)
    parser.add_argument('--estimate', action='store_true', help='Estimate number of items before cloning')
    parser.add_argument('--jobs', type=int, default=max(4, min(16, (os.cpu_count() or 4))), help='Parallel jobs for wget2')
    # JS behavior: default is allow JS; use --disable-js to strip/block
    parser.add_argument('--disable-js', action='store_true', help='Disable JavaScript (strip scripts and set CSP)')
    # Back-compat: accept --allow-js (no-op) if present
    parser.add_argument('--allow-js', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--run-built', action='store_true', help='Run the built image (requires --build)')
    parser.add_argument('--serve-folder', action='store_true', help='Serve directly from folder (nginx:alpine)')
    parser.add_argument('--open-browser', action='store_true', help='Open the URL after starting container')
    # Enhanced compatibility / prerendering
    parser.add_argument('--prerender', action='store_true', help='After clone, prerender dynamic pages with Playwright (optional dependency)')
    parser.add_argument('--prerender-max-pages', type=int, default=40, help='Maximum pages to prerender (default: 40)')
    parser.add_argument('--capture-api', action='store_true', help='Capture JSON API responses during prerender into _api/ directory')
    parser.add_argument('--hook-script', default=None, help='Path to a Python script exposing on_page(page, url, context) for prerender customization')
    parser.add_argument('--no-url-rewrite', action='store_true', help='Disable rewriting absolute origin URLs to relative in prerendered content')
    # Router interception options
    parser.add_argument('--router-intercept', action='store_true', help='Intercept SPA client-side router (history API) to discover additional routes during prerender')
    parser.add_argument('--router-include-hash', action='store_true', help='Treat distinct #hash fragments as separate routes when intercepting')
    parser.add_argument('--router-max-routes', type=int, default=200, help='Maximum additional routes discovered via router interception (default: 200)')
    parser.add_argument('--router-settle-ms', type=int, default=350, help='Millis to wait after initial load for automatic route pushes before snapshot (default: 350)')
    parser.add_argument('--router-wait-selector', default=None, help='Optional CSS selector to await after each intercepted route before snapshotting')
    parser.add_argument('--router-allow', default=None, help='Comma-separated regex patterns; only matching routes are kept (applied after include-hash normalization)')
    parser.add_argument('--router-deny', default=None, help='Comma-separated regex patterns; matching routes are discarded')
    parser.add_argument('--router-quiet', action='store_true', help='Suppress per-route discovery log lines while still counting routes')
    parser.add_argument('--no-manifest', action='store_true', help='Skip writing clone_manifest.json and summary augmentation')
    parser.add_argument('--checksums', action='store_true', help='Compute SHA256 checksums for mirrored HTML and captured API JSON (adds time)')
    parser.add_argument('--checksum-ext', default=None, help='Comma-separated extra file extensions to also checksum (e.g. css,js,png)')
    parser.add_argument('--verify-checksums', action='store_true', help='[Deprecated alias] Verify manifest checksums (fast mode)')
    parser.add_argument('--verify-after', action='store_true', help='Verify manifest after clone (fast unless --verify-deep)')
    parser.add_argument('--verify-deep', action='store_true', help='Deep verification (do not skip missing)')
    parser.add_argument('--verify-fast', action='store_true', help='Alias of --verify-after (fast mode)')
    parser.add_argument('--selftest-verification', action='store_true', help='Run internal verification parsing self-test and exit')
    parser.add_argument('--profile', action='store_true', help='Emit simple JSON with elapsed phase timing metrics at end')

    args = parser.parse_args(argv)

    if args.selftest_verification:
        _selftest_verification_parsing(); return 0

    if args.verify_fast:
        args.verify_after = True

    if not is_wget2_available():
        print('Error: wget2 is required but not found. See https://gitlab.com/gnuwget/wget2#installation')
        return 2

    output_folder = os.path.join(args.dest, args.docker_name or 'site')
    os.makedirs(output_folder, exist_ok=True)
    print(f"[clone] Output: {output_folder}")

    # Estimate
    if args.estimate:
        try:
            est = _cli_estimate_with_spider(args.url)
            if est:
                print(f"[clone] Estimated items: ~{est}")
        except Exception as e:
            print(f"[warn] Estimate failed: {e}")

    # Build wget2 command
    wget_cmd = [
        'wget2','-e','robots=off','--mirror','--convert-links','--adjust-extension',
        '--page-requisites','--no-parent','--continue','--progress=dot:mega',
        args.url,'-P', output_folder
    ]
    if args.jobs and args.jobs > 1:
        wget_cmd += ['-j', str(int(args.jobs))]
    if args.size_cap:
        b = parse_size_to_bytes(args.size_cap)
        if b:
            wget_cmd += ['--quota', human_quota_suffix(b)]
    if args.throttle:
        r = parse_rate_to_bps(args.throttle)
        if r:
            wget_cmd += ['--limit-rate', human_rate_suffix(r)]
    if args.auth_user:
        wget_cmd += ['--http-user', args.auth_user]
        if args.auth_pass is not None:
            wget_cmd += ['--http-password', args.auth_pass]
            print('[info] Using HTTP authentication (password not shown).')

    import time as _time
    _t0 = _time.time()
    print('[clone] Running wget2...')
    rc = _cli_run_stream(wget_cmd)
    if rc != 0:
        print(f"[error] wget2 exited with code {rc}")
        return rc
    _t_clone_end = _time.time()
    print('[clone] Complete.')

    # Prepare Dockerfile & nginx.conf
    site_root = find_site_root(output_folder)
    # Optional prerender step
    _t_prer_start = None; _t_prer_end = None
    if args.prerender:
        _t_prer_start = _time.time()
        try:
            _run_prerender(
                start_url=args.url,
                site_root=site_root,
                output_folder=output_folder,
                max_pages=max(1, args.prerender_max_pages),
                capture_api=args.capture_api,
                hook_script=args.hook_script,
                rewrite_urls=(not args.no_url_rewrite),
                api_capture_cb=(lambda n: print(f"[prerender] API JSON captured: {n}")) if args.capture_api else None,
                router_intercept=args.router_intercept,
                router_include_hash=args.router_include_hash,
                router_max_routes=max(1, args.router_max_routes),
                router_settle_ms=max(0, args.router_settle_ms),
                router_wait_selector=args.router_wait_selector or None,
                router_allow=[p.strip() for p in (args.router_allow.split(',') if args.router_allow else []) if p.strip()] or None,
                router_deny=[p.strip() for p in (args.router_deny.split(',') if args.router_deny else []) if p.strip()] or None,
                router_route_cb=(lambda n: print(f"[prerender] Router routes discovered: {n}")) if args.router_intercept else None,
                router_quiet=args.router_quiet
            )
        except Exception as e:
            print(f"[warn] Prerender failed: {e}")
        _t_prer_end = _time.time()
    # Optional checksum + manifest (headless mode lightweight version)
    if not args.no_manifest:
        try:
            import json, hashlib
            extra_ext_list = [e.strip().lower().lstrip('.') for e in (args.checksum_ext.split(',') if args.checksum_ext else []) if e.strip()]
            manifest = {
                'url': args.url,
                'docker_name': args.docker_name,
                'output_folder': output_folder,
                'prerender': bool(args.prerender),
                'capture_api': bool(args.capture_api),
                'router_intercept': bool(args.router_intercept),
                'checksums_included': bool(args.checksums),
                'checksum_extra_extensions': extra_ext_list,
            }
            if args.checksums:
                def _headless_progress(processed, total):
                    print(f"[checksums] {processed}/{total} ({int(processed*100/total)}%)")
                manifest['checksums_sha256'] = compute_checksums(output_folder, extra_ext_list, progress_cb=_headless_progress)
            manifest_path = os.path.join(output_folder, 'clone_manifest.json')
            with open(manifest_path, 'w', encoding='utf-8') as mf:
                json.dump(manifest, mf, indent=2)
            print('[manifest] clone_manifest.json written.')
            if (args.verify_checksums or args.verify_after) and args.checksums:
                print('[verify] running checksum verification...')
                fast = not args.verify_deep
                passed, stats = run_verification(
                    manifest_path,
                    fast=fast,
                    docker_name=args.docker_name,
                    project_dir=output_folder,
                    readme=True,
                    output_cb=lambda line: print(line)
                )
                if passed:
                    print('[verify] checksum verification PASSED')
                else:
                    print('[verify] checksum verification FAILED')
        except Exception as e:
            print(f"[warn] Failed to write manifest: {e}")
    if args.disable_js:
        try:
            # reuse same stripper
            def _strip(root):
                import re, os
                script_re = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
                for base, _, files in os.walk(root):
                    for fn in files:
                        if fn.lower().endswith((".html",".htm")):
                            p=os.path.join(base,fn)
                            try:
                                with open(p,'r',encoding='utf-8',errors='ignore') as f: txt=f.read()
                                new_txt=script_re.sub('',txt)
                                if new_txt!=txt:
                                    with open(p,'w',encoding='utf-8') as f: f.write(new_txt)
                            except Exception:
                                continue
            _strip(site_root)
            print('[info] JavaScript disabled: stripped <script> tags from HTML files.')
        except Exception as e:
            print(f'[warn] Failed to strip JS: {e}')
    rel_root = os.path.relpath(site_root, output_folder)
    dockerfile_path = os.path.join(output_folder, 'Dockerfile')
    with open(dockerfile_path, 'w', encoding='utf-8') as f:
        f.write(
            'FROM nginx:alpine\n'
            f'COPY {rel_root}/ /usr/share/nginx/html\n'
            'COPY nginx.conf /etc/nginx/conf.d/default.conf\n'
            f'EXPOSE {int(args.container_port)}\n'
            'CMD ["nginx", "-g", "daemon off;"]\n'
        )
    nginx_conf_path = os.path.join(output_folder, 'nginx.conf')
    with open(nginx_conf_path, 'w', encoding='utf-8') as f:
        parts = [
            'server {\n',
            f'    listen {int(args.container_port)};\n',
            '    server_name localhost;\n',
            '    root /usr/share/nginx/html;\n',
            '    index index.html;\n',
        ]
        if args.disable_js:
            parts.append('    add_header Content-Security-Policy "script-src \'none\'; frame-src \'none\'" always;\n')
        parts.append('    location / { try_files $uri $uri/ =404; }\n')
        parts.append('}\n')
        f.write(''.join(parts))
    print('[build] Dockerfile and nginx.conf created.')

    docker_success = False
    image = (args.docker_name or 'site').strip()
    _t_build_start = None; _t_build_end = None
    if args.build:
        if not docker_available():
            print('[warn] Docker not installed. Skipping build.')
        else:
            _t_build_start = _time.time()
            print(f"[build] docker build -t {image} {output_folder}")
            rc = _cli_run_stream(['docker','build','-t', image, output_folder])
            docker_success = (rc == 0)
            if not docker_success:
                print('[error] Docker build failed.')
            _t_build_end = _time.time()

    # Optional run
    started = False
    url_out = None
    if args.run_built and docker_success:
        bind_ip = normalize_ip(args.bind_ip)
        host_p = int(args.host_port)
        cont_p = int(args.container_port)
        cmd = ['docker','run','-d','-p', f'{bind_ip}:{host_p}:{cont_p}', image]
        print('[run] ' + ' '.join(cmd))
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            cid = res.stdout.strip()
            host = 'localhost' if bind_ip == '0.0.0.0' else bind_ip
            url_out = f'http://{host}:{host_p}'
            started = True
            print(f'[run] Started container {cid} at {url_out}')
        else:
            print(f"[error] Failed to run built image: {res.stderr.strip()}")

    if args.serve_folder and docker_available():
        bind_ip = normalize_ip(args.bind_ip)
        host_p = int(args.host_port)
        cont_p = int(args.container_port)
        conf_path = os.path.join(site_root, f'.folder.default.{cont_p}.conf')
        try:
            with open(conf_path,'w',encoding='utf-8') as f:
                f.write(
                    'server {\n'
                    f'    listen {cont_p};\n'
                    '    server_name localhost;\n'
                    '    root /usr/share/nginx/html;\n'
                    '    index index.html;\n'
                    '    location / { try_files $uri $uri/ =404; }\n'
                    '}\n'
                )
        except Exception as e:
            print(f'[error] Failed creating folder nginx conf: {e}')
            return 1
        cmd = ['docker','run','-d','-p', f'{bind_ip}:{host_p}:{cont_p}',
               '-v', f'{site_root}:/usr/share/nginx/html',
               '-v', f'{conf_path}:/etc/nginx/conf.d/default.conf:ro',
               'nginx:alpine']
        print('[run] ' + ' '.join(cmd))
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            cid = res.stdout.strip()
            host = 'localhost' if bind_ip == '0.0.0.0' else bind_ip
            url_out = f'http://{host}:{host_p}'
            started = True
            print(f'[run] Serving from folder at {url_out} (ID: {cid})')
        else:
            print(f"[error] Failed to serve from folder: {res.stderr.strip()}")

    if started and args.open_browser and url_out:
        try:
            webbrowser.open(url_out)
        except Exception:
            pass

    # Write README with headless examples (appends existing content later in code)
    if args.profile:
        prof = {}
        try:
            prof['clone_seconds'] = round((_t_clone_end - _t0), 4)
            if _t_prer_start and _t_prer_end:
                prof['prerender_seconds'] = round((_t_prer_end - _t_prer_start), 4)
            if _t_build_start and _t_build_end:
                prof['build_seconds'] = round((_t_build_end - _t_build_start), 4)
            prof['total_seconds'] = round((_time.time() - _t0), 4)
            prof['parallel_jobs'] = int(args.jobs or 1)
            prof['checksums'] = bool(args.checksums)
            prof['prerender'] = bool(args.prerender)
            prof['build'] = bool(args.build)
            import json
            print('\n[profile] ' + json.dumps(prof, indent=2))
        except Exception:
            pass
    return 0

def _cli_run_stream(cmd: list[str]) -> int:
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    except Exception as e:
        print(f"[error] Failed to start: {e}")
        return 1
    try:
        stream = proc.stdout
        if stream is not None:
            for line in stream:
                if not line:
                    continue
                print(line.rstrip())
    finally:
        proc.wait()
    return proc.returncode or 0

def _cli_estimate_with_spider(url: str) -> int:
    try:
        proc = subprocess.Popen(['wget2','--spider','-e','robots=off','--recursive','--no-parent', url],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    except Exception:
        return 0
    seen = set()
    stream = proc.stdout
    if stream is not None:
        for line in stream:
            if not line:
                continue
            line=line.strip()
            if line.startswith('--'):
                parts=line.split()
                if len(parts)>=2 and parts[1].startswith('http'):
                    seen.add(parts[1])
            elif 'http://' in line or 'https://' in line:
                for tok in line.split():
                    if tok.startswith('http://') or tok.startswith('https://'):
                        seen.add(tok)
    proc.wait()
    return len(seen)

# If invoked headless, run before importing Qt
if __name__ == '__main__':
    # Standalone internal self-test bypasses all other logic
    if '--selftest-verification' in sys.argv and '--headless' not in sys.argv:
        _selftest_verification_parsing(); sys.exit(0)
    if '--headless' in sys.argv:
        argv = [a for a in sys.argv[1:] if a != '--headless']
        # Allow selftest to skip dependency install to avoid network
        if '--selftest-verification' in argv:
            # still parse through headless_main (it short-circuits before heavy work)
            sys.exit(headless_main(argv))
        # Ensure mandatory Python dependency for headless: browser_cookie3
        try:
            importlib.import_module('browser_cookie3')
        except Exception:
            print('[deps] Installing browser_cookie3...')
            rc = subprocess.call([sys.executable, '-m', 'pip', 'install', 'browser_cookie3'])
            if rc != 0:
                print('[error] Failed to install browser_cookie3. Please install it and retry.')
                sys.exit(2)
        sys.exit(headless_main(argv))

# After headless early-exit, import Qt for GUI definitions below
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QTextEdit, QCheckBox, QComboBox, QSpinBox, QInputDialog, QFrame, QSizePolicy,
    QMessageBox, QScrollArea, QLayout, QDialog, QProgressBar, QSplitter, QSplitterHandle
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSettings
from PySide6.QtGui import QGuiApplication, QFontMetrics, QPixmap, QIcon

def image_exists_locally(image_name: str) -> bool:
    if not image_name:
        return False
    try:
        res = subprocess.run(["docker", "image", "inspect", image_name], capture_output=True, text=True)
        return res.returncode == 0
    except Exception:
        return False

def find_icon(filename):
    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    candidates = [
        os.path.join(script_dir, "images", filename),
        os.path.join(script_dir, filename),
        os.path.join(os.getcwd(), "images", filename),
        os.path.join(os.getcwd(), filename),
        f"/mnt/data/{filename}",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

def load_icon_label(filename, size=56, alt_text=""):
    lbl = QLabel()
    path = find_icon(filename)
    if path:
        pm = QPixmap(path).scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        lbl.setPixmap(pm)
    else:
        lbl.setText(alt_text or filename)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet("background: transparent;")
    return lbl

def divider():
    line = QFrame()
    line.setObjectName("divider")
    line.setFrameShape(QFrame.Shape.NoFrame)
    line.setFixedHeight(1)
    return line

class CollapsibleSection(QWidget):
    def __init__(self, title: str, start_collapsed: bool = True, parent=None):
        super().__init__(parent)
        self._collapsed = start_collapsed
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        # Header bar
        self.header = QFrame(); hl = QHBoxLayout(self.header); hl.setContentsMargins(0,0,0,0); hl.setSpacing(6)
        self.chevron = QLabel("▸" if start_collapsed else "▾")
        self.chevron.setFixedWidth(14)
        self.header_label = QLabel(title); self.header_label.setProperty("role", "section")
        hl.addWidget(self.chevron)
        hl.addWidget(self.header_label)
        hl.addStretch(1)
        try:
            self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        except Exception:
            pass
        v.addWidget(self.header)
        # Divider under header
        v.addWidget(divider())
        # Content container
        self.content = QFrame(); self.content.setContentsMargins(0,0,0,0)
        v.addWidget(self.content)
        self.set_collapsed(self._collapsed)
        # Click to toggle
        self.header.mousePressEvent = self._on_header_clicked

    def setContentLayout(self, layout: QLayout):
        self.content.setLayout(layout)

    def _on_header_clicked(self, event):
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool):
        self._collapsed = bool(collapsed)
        self.content.setVisible(not self._collapsed)
        # Update chevron indicator
        if hasattr(self, 'chevron'):
            self.chevron.setText("▸" if self._collapsed else "▾")

    def is_expanded(self) -> bool:
        return not self._collapsed


class GuardedSplitter(QSplitter):
    """QSplitter that clamps the handle to respect each pane's minimum width.
    Prevents a pane from sliding visually under its sibling when dragging.
    """
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._locked_pos = None  # type: int | None

    def setLockedPosition(self, pos: int | None):
        self._locked_pos = int(pos) if pos is not None else None
        self.enforce_locked()

    def enforce_locked(self):
        if self._locked_pos is None:
            return
        try:
            if self.orientation() != Qt.Orientation.Horizontal or self.count() < 2:
                return
            # Derive clamped position and apply sizes
            try:
                handle = int(self.handleWidth())
            except Exception:
                handle = 8
            total = max(0, int(self.width()))
            left_min = max(0, int(self.widget(0).minimumWidth()))
            right_min = max(0, int(self.widget(1).minimumWidth()))
            safe_gap_right = 8
            min_pos = left_min
            max_pos = max(min_pos, total - right_min - handle - safe_gap_right)
            pos = max(min_pos, min(int(self._locked_pos), max_pos))
            right = max(0, total - pos - handle)
            if right < right_min:
                right = right_min
                pos = max(0, total - right - handle)
            self.setSizes([pos, right])
        except Exception:
            pass

    def moveSplitter(self, pos: int, index: int) -> None:
        try:
            if self.orientation() == Qt.Orientation.Horizontal and self.count() >= 2:
                try:
                    handle = int(self.handleWidth())
                except Exception:
                    handle = 8
                total = max(0, int(self.width()))
                left_min = max(0, int(self.widget(0).minimumWidth()))
                right_min = max(0, int(self.widget(1).minimumWidth()))
                # Add a small safety gap so child borders never touch the handle visually
                safe_gap_left = 0
                safe_gap_right = 8
                min_pos = left_min + safe_gap_left
                max_pos = max(min_pos, total - right_min - handle - safe_gap_right)
                # Respect locked position if set
                if self._locked_pos is not None:
                    pos = self._locked_pos
                pos = max(min_pos, min(int(pos), max_pos))
        except Exception:
            pass
        super().moveSplitter(pos, index)

    def createHandle(self) -> QSplitterHandle:
        try:
            return GuardedHandle(self.orientation(), self)
        except Exception:
            return super().createHandle()


class GuardedHandle(QSplitterHandle):
    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)

    def mouseMoveEvent(self, event):
        try:
            sp: GuardedSplitter = self.splitter()  # type: ignore
            if sp is not None:
                if sp.orientation() == Qt.Orientation.Horizontal:
                    if getattr(sp, '_locked_pos', None) is not None:
                        # If locked, ignore dragging
                        event.accept();
                        return
                    # Map handle-local pos to splitter coords
                    x = self.mapTo(sp, event.pos()).x()
                    # Use first index (0) since exact handle index API may differ across Qt versions
                    try:
                        sp.moveSplitter(x, 0)
                    except Exception:
                        pass
                    event.accept()
                    return
        except Exception:
            pass
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        try:
            sp: GuardedSplitter = self.splitter()  # type: ignore
            if sp is not None and getattr(sp, '_locked_pos', None) is not None:
                event.accept();
                return
        except Exception:
            pass
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        try:
            sp: GuardedSplitter = self.splitter()  # type: ignore
            if sp is not None and getattr(sp, '_locked_pos', None) is not None:
                event.accept();
                return
        except Exception:
            pass
        super().mouseReleaseEvent(event)

# ---------- clone/build worker ----------
class CloneThread(QThread):
    progress = Signal(str)
    total_progress = Signal(int, str)  # (percent, phase)
    bandwidth = Signal(str)  # human readable current transfer rate
    api_capture = Signal(int)  # count of API JSON responses captured
    router_count = Signal(int)  # number of router-discovered routes (accepted)
    checksum_progress = Signal(int)  # percent for checksum hashing phase (if enabled)
    finished = Signal(str, bool, bool)  # (log, docker_build_success, clone_success)

    def __init__(self, url, docker_name, save_path, build_docker,
                 host_port=DEFAULT_HOST_PORT, size_cap=None, throttle=None, host_ip="127.0.0.1",
                 container_port=DEFAULT_CONTAINER_PORT, http_user=None, http_password=None,
                 pre_existing_count=0, pre_partial_count=0,
                 estimate_first=False, parallel_jobs=1,
                 disable_js=False,
                 prerender=False, prerender_max_pages=DEFAULT_PRERENDER_MAX_PAGES, capture_api=False, hook_script=None, rewrite_urls=True,
                 router_intercept=False, router_include_hash=False, router_max_routes=DEFAULT_ROUTER_MAX_ROUTES, router_settle_ms=DEFAULT_ROUTER_SETTLE_MS, router_wait_selector=None,
                 router_allow=None, router_deny=None,
                 cookies_file: str | None = None,
                 no_manifest: bool = False,
                 checksums: bool = False,
                 checksum_extra_ext: list[str] | None = None):
        super().__init__()
        self.url = url
        self.docker_name = docker_name.strip()
        self.save_path = save_path
        self.build_docker = build_docker
        self.host_port = host_port
        self.size_cap = size_cap  # bytes
        self.throttle = throttle  # bytes/sec
        self.host_ip = host_ip
        self.container_port = int(container_port)
        self.http_user = (http_user or "").strip() or None
        self.http_password = http_password or None
        self.pre_existing_count = int(pre_existing_count or 0)
        self.pre_partial_count = int(pre_partial_count or 0)
        self.estimate_first = bool(estimate_first)
        self.parallel_jobs = max(1, int(parallel_jobs or 1))
        self._stop_requested = False
        self._active_proc = None
        self._canceled = False
        self.disable_js = bool(disable_js)
        self.cookies_file = cookies_file
        # Enhanced compatibility options
        self.prerender = bool(prerender)
        self.prerender_max_pages = max(1, int(prerender_max_pages or 1))
        self.capture_api = bool(capture_api)
        self.hook_script = hook_script
        self.rewrite_urls = bool(rewrite_urls)
        self.router_intercept = bool(router_intercept)
        self.router_include_hash = bool(router_include_hash)
        self.router_max_routes = int(router_max_routes)
        self.router_settle_ms = int(router_settle_ms)
        self.router_wait_selector = router_wait_selector
        self.router_allow = router_allow
        self.router_deny = router_deny
        self._router_discovered_count = 0
        self.router_quiet = False  # set by GUI option if enabled
        self._api_captured_count = 0
        self._started_utc = datetime.utcnow()
        self.no_manifest = bool(no_manifest)
        self.checksums = bool(checksums)
        self.checksum_extra_ext = [e.lower().lstrip('.') for e in (checksum_extra_ext or []) if e]
        # phase timing (store simple floats)
        self._phase_start_time = {}
        self._phase_end_time = {}

    def request_stop(self):
        self._stop_requested = True
        proc = self._active_proc
        if proc:
            try:
                proc.terminate()
            except Exception:
                pass

    def run(self):
        log = []
        docker_success = False
        clone_success = False

        def _now_ts():
            return datetime.utcnow().strftime('%H:%M:%S')

        def log_msg(message: str, phase: str | None = None):
            """Emit a standardized progress line with timestamp and optional phase label."""
            if phase:
                line = f"[{_now_ts()}] [{phase}] {message}"
            else:
                line = f"[{_now_ts()}] {message}"
            log.append(line)
            self.progress.emit(line)

        # init overall progress tracking with dynamic optional phases
        phases = ["clone"]
        if self.prerender:
            phases.append("prerender")
        if self.checksums:
            phases.append("checksums")
        if self.build_docker:
            phases.append("build")
        phases.append("cleanup")
        self._phase_pct = {p: 0 for p in phases}
        # Base heuristic weights then adjust for presence of optional phases
        if self.build_docker:
            if self.prerender and self.checksums:
                weights = {"clone": 0.42, "prerender": 0.15, "checksums": 0.08, "build": 0.30, "cleanup": 0.05}
            elif self.prerender and not self.checksums:
                weights = {"clone": 0.45, "prerender": 0.15, "build": 0.35, "cleanup": 0.05}
            elif self.checksums and not self.prerender:
                weights = {"clone": 0.55, "checksums": 0.10, "build": 0.30, "cleanup": 0.05}
            else:
                weights = {"clone": 0.6, "build": 0.4, "cleanup": 0.05}
        else:
            if self.prerender and self.checksums:
                weights = {"clone": 0.58, "prerender": 0.20, "checksums": 0.12, "cleanup": 0.10}
            elif self.prerender and not self.checksums:
                weights = {"clone": 0.7, "prerender": 0.2, "cleanup": 0.1}
            elif self.checksums and not self.prerender:
                weights = {"clone": 0.75, "checksums": 0.15, "cleanup": 0.10}
            else:
                weights = {"clone": 0.9, "cleanup": 0.1}
        total_w = sum(weights.values()) or 1.0
        self._weights = {k: (v / total_w) for k, v in weights.items()}

        def emit_total(phase, pct):
            try:
                pct = max(0, min(100, int(pct)))
            except Exception:
                pct = 0
            # track start/end times
            import time as _time
            if phase not in self._phase_start_time and pct > 0:
                self._phase_start_time[phase] = _time.time()
            self._phase_pct[phase] = pct
            if pct >= 100:
                self._phase_end_time.setdefault(phase, _time.time())
            # recompute overall weighted total
            total = 0
            for ph, w in self._weights.items():
                total += (self._phase_pct.get(ph, 0) * w)
            total = int(round(total))
            self.total_progress.emit(total, phase)

        if not is_wget2_available():
            log_msg("Error: wget2 is not installed. Please install it and try again.")
            self.finished.emit("\n".join(log), docker_success, clone_success); return
        output_folder = os.path.join(self.save_path, self.docker_name if self.docker_name else "site")
        os.makedirs(output_folder, exist_ok=True)

        log_msg(f"Cloning {self.url} into {output_folder}")
        # Optional estimate prepass
        if self.estimate_first and not self._stop_requested:
            try:
                est = self._estimate_with_spider(self.url)
                if est > 0:
                    log_msg(f"Estimated items to fetch: ~{est}", phase="estimate")
                else:
                    log_msg("Estimate: could not determine item count (proceeding)", phase="estimate")
            except Exception as e:
                log_msg(f"Estimate failed: {e} (proceeding)", phase="estimate")
        if self._stop_requested:
            log_msg("Clone canceled before start.")
            self.finished.emit("\n".join(log), docker_success, clone_success); return
        emit_total("clone", 0)
        # Use wget2 exclusively for parallel downloads
        downloader = "wget2"
        wget_cmd = [
            downloader, "-e", "robots=off",
            "--mirror", "--convert-links", "--adjust-extension",
            "--page-requisites", "--no-parent",
            "--continue",
            "--progress=dot:mega",
            self.url, "-P", output_folder
        ]
        if self.cookies_file and os.path.exists(self.cookies_file):
            wget_cmd += ["--load-cookies", self.cookies_file]
        if self.parallel_jobs > 1:
            wget_cmd += ["-j", str(self.parallel_jobs)]
            log_msg(f"Using wget2 with {self.parallel_jobs} parallel jobs.", phase="clone")
        if self.size_cap: wget_cmd += ["--quota", human_quota_suffix(self.size_cap)]
        if self.throttle: wget_cmd += ["--limit-rate", human_rate_suffix(self.throttle)]
        if self.http_user:
            wget_cmd += ["--http-user", self.http_user]
            if self.http_password is not None:
                wget_cmd += ["--http-password", self.http_password]
            log_msg("Using HTTP authentication for cloning (credentials not shown).", phase="clone")

        try:
            if not self._run_wget_with_progress(wget_cmd, emit_total):
                self.finished.emit("\n".join(log), docker_success, clone_success); return
            log_msg("Cloning complete (100%).")
            clone_success = True
            emit_total("clone", 100)

            # Post-clone file counts (new vs existing)
            try:
                post_total, post_partials = count_files_and_partials(output_folder)
                new_files = max(0, post_total - self.pre_existing_count)
                log_msg(
                    f"Files: existing before={self.pre_existing_count}, partial before={self.pre_partial_count}, new downloaded={new_files}",
                    phase="clone")
            except Exception:
                pass
        except Exception as e:
            log_msg(f"Error running wget2: {e}")
            self.finished.emit("\n".join(log), docker_success, clone_success); return

        if self._stop_requested:
            log_msg("Clone canceled by user.")
            self.finished.emit("\n".join(log), docker_success, clone_success); return
        site_root = find_site_root(output_folder)
        # Optional prerender (performed before JS stripping / Docker build)
        if self.prerender and not self._stop_requested:
            try:
                log_msg(f"Starting prerender (max {self.prerender_max_pages} pages)...", phase="prerender")
                emit_total("prerender", 0)
                _run_prerender(
                    start_url=self.url,
                    site_root=site_root,
                    output_folder=output_folder,
                    max_pages=self.prerender_max_pages,
                    capture_api=self.capture_api,
                    hook_script=self.hook_script,
                    rewrite_urls=self.rewrite_urls,
                    progress_cb=self.progress.emit,
                    progress_percent_cb=lambda pct: emit_total("prerender", pct),
                    api_capture_cb=(lambda n: (setattr(self, '_api_captured_count', n), self.api_capture.emit(n))[1]) if self.capture_api else None,
                    router_intercept=self.router_intercept,
                    router_include_hash=self.router_include_hash,
                    router_max_routes=self.router_max_routes,
                    router_settle_ms=self.router_settle_ms,
                    router_wait_selector=self.router_wait_selector,
                    router_allow=self.router_allow,
                    router_deny=self.router_deny,
                    router_route_cb=(lambda n: (setattr(self, '_router_discovered_count', n), self.router_count.emit(n))[1]) if self.router_intercept else None,
                    router_quiet=self.router_quiet
                )
                log_msg("Prerender complete (100%).", phase="prerender")
            except Exception as e:
                log_msg(f"Prerender failed: {e}", phase="prerender")
        # Optionally strip scripts from HTML to prevent JS execution
        if self.disable_js:
            try:
                scanned, stripped = self._strip_js_from_html(site_root)
                log_msg(f"JavaScript disabled: stripped <script> tags from {stripped}/{scanned} HTML files.", phase="post")
            except Exception as e:
                log_msg(f"Warning: failed to strip JS: {e}", phase="post")
        rel_root = os.path.relpath(site_root, output_folder)
        log_msg(f"Site root detected: {rel_root}", phase="post")

        # Dockerfile & nginx.conf tuned to container_port
        dockerfile_path = os.path.join(output_folder, "Dockerfile")
        with open(dockerfile_path, "w", encoding="utf-8") as f:
            f.write(
                "FROM nginx:alpine\n"
                f"COPY {rel_root}/ /usr/share/nginx/html\n"
                "COPY nginx.conf /etc/nginx/conf.d/default.conf\n"
                f"EXPOSE {self.container_port}\n"
                "CMD [\"nginx\", \"-g\", \"daemon off;\"]\n"
            )
        log_msg("Dockerfile created.", phase="build")

        nginx_conf_path = os.path.join(output_folder, "nginx.conf")
        with open(nginx_conf_path, "w", encoding="utf-8") as f:
            parts = [
                "server {\n",
                f"    listen {self.container_port};\n",
                "    server_name localhost;\n",
                "    root /usr/share/nginx/html;\n",
                "    index index.html;\n",
            ]
            if self.disable_js:
                parts.append("    add_header Content-Security-Policy \"script-src 'none'; frame-src 'none'\" always;\n")
            parts.append("    location / { try_files $uri $uri/ =404; }\n")
            parts.append("}\n")
            f.write("".join(parts))
        log_msg("nginx.conf created.", phase="build")

        # Optional docker build with cleanup after success
        if self.build_docker and not self._stop_requested:
            if not self.docker_name:
                log_msg("Skipping build: Docker image name is required when 'Build image' is checked.")
            elif docker_available():
                try:
                    log_msg("Building Docker image (0%)...", phase="build")
                    emit_total("build", 0)
                    if self._run_docker_build_with_progress(output_folder, self.docker_name, emit_total):
                        docker_success = True
                        log_msg("Docker build complete (100%). Cleaning up build inputs...", phase="build")
                        emit_total("build", 100)
                        self._cleanup_with_progress(output_folder, emit_total, keep_rel_root=rel_root)
                    else:
                        log_msg(f"Install Docker with:\n{docker_install_instructions()}", phase="build")
                except Exception as e:
                    log_msg(f"Error building Docker image: {e}", phase="build")
            else:
                log_msg("Docker not installed.", phase="build")
                log_msg(f"Install with:\n{docker_install_instructions()}", phase="build")

        # README (last, reflects final state)
        abs_output = os.path.abspath(output_folder)
        image_tag = (self.docker_name or "site").strip()
        os.makedirs(output_folder, exist_ok=True)  # recreate if cleanup emptied it
        bind_ip_for_cmd = self.host_ip or "127.0.0.1"
        abs_site_root = os.path.join(abs_output, rel_root)
        with open(os.path.join(output_folder, f"README_{image_tag or 'site'}.md"), "w", encoding="utf-8") as f:
            f.write(
                f"# Docker Website Container\n\n"
                f"## Requirements\n"
                f"- wget2 (used for cloning; supports parallel downloads)\n"
                f"- Docker (optional; required to build and run the container)\n"
                f"- Python 3.8+ (for headless CLI usage)\n"
                f"- Optional: browser_cookie3 (for importing browser cookies)\n\n"
                f"## Features\n"
                f"- Resumable cloning (wget2 --continue) with parallel downloads\n"
                f"- Optional pre-clone estimate (spider)\n"
                f"- Size quota and bandwidth throttling\n"
                f"- Optional JavaScript disabling (strip <script> and enforce CSP)\n"
                f"- Windows and Linux/macOS run instructions\n"
                f"- Headless (CLI) mode for automation\n\n"
                f"## Project Location\n{abs_output}\n\n"
                f"## Image Status\n"
                + (f"Built locally as: `{image_tag}` (check with `docker images`).\n\n"
                   if docker_success else
                   f"Not built yet. To build locally: `docker build -t {image_tag} .`\n\n")
                + "## How to Run\n"
                  f"- Run created container (if built):\n"
                  f"  ```bash\ndocker run -d -p {bind_ip_for_cmd}:{self.host_port}:{self.container_port} {image_tag}\n```\n"
                  f"- Serve directly from this folder (no build):\n"
                  f"  ```bash\n# create a temp nginx file that listens on your chosen container port\ncat > _folder.default.conf <<'CONF'\nserver {{\n    listen {self.container_port};\n    server_name localhost;\n    root /usr/share/nginx/html;\n    index index.html;\n    location / {{ try_files $uri $uri/ =404; }}\n}}\nCONF\n\ndocker run -d -p {bind_ip_for_cmd}:{self.host_port}:{self.container_port} \\\n  -v \"{abs_site_root}\":/usr/share/nginx/html \\\n  -v \"$(pwd)/_folder.default.conf\":/etc/nginx/conf.d/default.conf:ro \\\n  nginx:alpine\n```\n"
                  f"- Once running, open: http://{('localhost' if bind_ip_for_cmd=='0.0.0.0' else bind_ip_for_cmd)}:{self.host_port}\n"
            )
            # Additional hint using detected site root for folder mode
            f.write(
                "\n\n"
                f"Note: Detected site root: {abs_site_root}\n"
                f"You can use it for folder mode mounts if needed:\n\n"
                f"```bash\n"
                f"docker run -d -p {bind_ip_for_cmd}:{self.host_port}:{self.container_port} \\\n"
                f"  -v \"{abs_site_root}\":/usr/share/nginx/html \\\n"
                f"  -v \"$(pwd)/_folder.default.conf\":/etc/nginx/conf.d/default.conf:ro \\\n"
                f"  nginx:alpine\n```\n"
            )
            # wget2 note
            f.write(
                "\n\n"
                "### wget2\n"
                "This tool uses `wget2` exclusively for mirroring and parallel downloads.\n"
                "If cloning failed due to missing wget2, install it via your OS package manager.\n"
            )
            # Windows guidance
            ps = (
                "\n\n### Windows (PowerShell) Notes\n"
                "The commands above are for Linux/macOS shells. On Windows PowerShell, use the following patterns.\n\n"
                "- Create the nginx config file:\n\n"
                "```powershell\n"
                "$conf = @'\n"
                "server {\n"
                f"    listen {self.container_port};\n"
                "    server_name localhost;\n"
                "    root /usr/share/nginx/html;\n"
                "    index index.html;\n"
                "    location / { try_files $uri $uri/ =404; }\n"
                "}\n"
                "'@\n"
                "Set-Content -Path _folder.default.conf -Value $conf -NoNewline\n"
                "```\n\n"
                "- Run (folder mode) with Windows path mapping (adjust the path as needed):\n\n"
                "```powershell\n"
                f"docker run -d -p {bind_ip_for_cmd}:{self.host_port}:{self.container_port} `\n"
                f"  -v \"{abs_site_root}\":/usr/share/nginx/html `\n"
                "  -v \"$PWD\\_folder.default.conf\":/etc/nginx/conf.d/default.conf:ro `\n"
                "  nginx:alpine\n"
                "```\n\n"
                "- For a built image, replace the -v lines with the image name:\n\n"
                "```powershell\n"
                f"docker run -d -p {bind_ip_for_cmd}:{self.host_port}:{self.container_port} {image_tag}\n"
                "```\n\n"
            "- wget2 on Windows: Consider installing via MSYS2 (`pacman -S mingw-w64-ucrt-x86_64-wget2`) or building from source.\n"
            )
            f.write(ps)
            # Windows quick copy commands
            f.write(
                "\n\n### Windows Quick Copy Commands (PowerShell)\n"
                "Copy and paste these directly into PowerShell. Adjust paths/ports as needed.\n\n"
                "- Folder mode (two commands):\n\n"
                "```powershell\n"
                "$conf = @'\n"
                "server {\n"
                f"    listen {self.container_port};\n"
                "    server_name localhost;\n"
                "    root /usr/share/nginx/html;\n"
                "    index index.html;\n"
                "    location / { try_files $uri $uri/ =404; }\n"
                "}\n"
                "'@\n"
                "Set-Content -Path _folder.default.conf -Value $conf -NoNewline\n"
                f"docker run -d -p {bind_ip_for_cmd}:{self.host_port}:{self.container_port} `\n"
                f"  -v \"{abs_site_root}\":/usr/share/nginx/html `\n"
                "  -v \"$PWD\\_folder.default.conf\":/etc/nginx/conf.d/default.conf:ro `\n"
                "  nginx:alpine\n"
                "```\n\n"
                "- Built image:\n\n"
                "```powershell\n"
                f"docker run -d -p {bind_ip_for_cmd}:{self.host_port}:{self.container_port} {image_tag}\n"
                "```\n"
            )
            if self.http_user:
                f.write(
                    "\n\n## Security Note\n"
                    "If you used HTTP authentication during cloning, be aware that passing credentials "
                    "on the command line can expose them to other local users via process listings.\n"
                    "For stricter security, consider using a temporary .wgetrc or .netrc file and pointing wget2 to it.\n"
                )
            # Headless CLI usage
            f.write(
                "\n\n## Headless (CLI) Usage\n"
                "Run without the GUI using Python. Requires wget2 (and Docker for build/run).\n\n"
                "### Linux/macOS\n"
                f"```bash\n"
                f"python cw2dt.py --headless --url '{self.url}' --dest '{self.save_path}' --docker-name '{image_tag}' \\\n"
                f"  --jobs 8 --estimate --build --run-built --bind-ip {bind_ip_for_cmd} --host-port {self.host_port} --container-port {self.container_port}\n"
                f"```\n\n"
                "Serve directly from folder (no build):\n\n"
                f"```bash\n"
                f"python cw2dt.py --headless --url '{self.url}' --dest '{self.save_path}' --docker-name '{image_tag}' \\\n"
                f"  --jobs 8 --estimate --serve-folder --bind-ip {bind_ip_for_cmd} --host-port {self.host_port} --container-port {self.container_port}\n"
                f"```\n\n"
                "### Windows (PowerShell)\n"
                f"```powershell\n"
                f"py cw2dt.py --headless --url \"{self.url}\" --dest \"{self.save_path}\" --docker-name \"'{image_tag}'\" `\n"
                f"  --jobs 8 --estimate --build --run-built --bind-ip {bind_ip_for_cmd} --host-port {self.host_port} --container-port {self.container_port}\n"
                f"```\n\n"
                "Serve directly from folder (no build):\n\n"
                f"```powershell\n"
                f"py cw2dt.py --headless --url \"{self.url}\" --dest \"{self.save_path}\" --docker-name \"{image_tag}\" `\n"
                f"  --jobs 8 --estimate --serve-folder --bind-ip {bind_ip_for_cmd} --host-port {self.host_port} --container-port {self.container_port}\n"
                f"```\n"
            )
            # Troubleshooting
            f.write(
                "\n\n## Troubleshooting\n"
                "- wget2 missing: Use the top bar buttons to copy install commands, or see https://gitlab.com/gnuwget/wget2#installation.\n"
                "- Docker permission denied (Linux): Add your user to the `docker` group or run with `sudo`. Then re-login.\n"
                "- Windows path mounts: Use double quotes for `-v` host paths; prefer PowerShell examples provided.\n"
                "- Parallel jobs: If your wget2 build doesn\'t support `-j`, disable parallel downloads in Advanced or set jobs=1.\n"
                "- Dependency install failed: Use the Dependency bar to copy commands and run them in an elevated shell, then click Retry.\n"
            )
        log_msg("README created.")

        # Write machine-consumable manifest + concise summary (best-effort) unless disabled
        if not self.no_manifest:
            try:
                import json
                manifest = {
                "url": self.url,
                "docker_name": self.docker_name,
                "output_folder": os.path.abspath(output_folder),
                "started_utc": self._started_utc.isoformat() + 'Z',
                "completed_utc": datetime.utcnow().isoformat() + 'Z',
                "clone_success": clone_success,
                "docker_built": docker_success,
                "prerender": self.prerender,
                "prerender_max_pages": self.prerender_max_pages if self.prerender else None,
                "api_capture": self.capture_api if self.prerender else False,
                "api_captured_count": self._api_captured_count if self.capture_api else 0,
                "router_intercept": self.router_intercept if self.prerender else False,
                "router_routes": self._router_discovered_count if (self.prerender and self.router_intercept) else 0,
                "router_include_hash": self.router_include_hash if self.router_intercept else False,
                "router_max_routes": self.router_max_routes if self.router_intercept else None,
                "router_allow": self.router_allow or [],
                "router_deny": self.router_deny or [],
                "router_quiet": self.router_quiet if self.router_intercept else False,
                "disable_js": self.disable_js,
                "parallel_jobs": self.parallel_jobs,
                "size_cap_bytes": self.size_cap,
                "throttle_bytes_per_sec": self.throttle,
                "http_auth_used": bool(self.http_user),
            }
                # Optionally compute checksums (HTML + API JSON + extra ext)
                if self.checksums:
                    emit_total("checksums", 0)
                    def _gui_progress(processed, total):
                        pct = int(processed * 100 / total) if total else 100
                        try:
                            self.progress.emit(f"Checksums: {processed}/{total} ({pct}%)")
                        except Exception: pass
                        try:
                            self.checksum_progress.emit(pct)
                        except Exception: pass
                        emit_total("checksums", pct)
                    checks = compute_checksums(output_folder, self.checksum_extra_ext, progress_cb=_gui_progress)
                    manifest['checksums_sha256'] = checks
                    if self.checksum_extra_ext:
                        manifest['checksum_extra_extensions'] = self.checksum_extra_ext
                    try:
                        self.progress.emit("Checksums complete (100%).")
                    except Exception:
                        pass
                # Phase timing summary (seconds)
                if self._phase_start_time:
                    import math
                    timings = {}
                    for ph, st in self._phase_start_time.items():
                        et = self._phase_end_time.get(ph)
                        if et:
                            timings[ph] = round(et - st, 2)
                    if timings:
                        manifest['phase_durations_seconds'] = timings
                # API capture note if enabled but none found
                if manifest.get('api_capture') and not manifest.get('api_captured_count'):
                    manifest['api_capture_note'] = 'API capture enabled but no JSON responses matched filtering.'
                with open(os.path.join(output_folder, 'clone_manifest.json'), 'w', encoding='utf-8') as mf:
                    json.dump(manifest, mf, indent=2)
                readme_path = os.path.join(output_folder, f"README_{(self.docker_name or 'site').strip()}.md")
                try:
                    repro = self._build_repro_command()
                    with open(readme_path, 'a', encoding='utf-8') as rf:
                        rf.write("\n\n---\n## Clone Summary\n")
                        rf.write(f"- Prerender: {'yes' if self.prerender else 'no'}\n")
                        if self.prerender:
                            rf.write(f"  - API captured: {self._api_captured_count}\n")
                            if self.router_intercept:
                                rf.write(f"  - Router routes: {self._router_discovered_count}\n")
                        if self.checksums:
                            rf.write("  - Checksums: yes\n")
                            if self.checksum_extra_ext:
                                rf.write(f"    * Extra extensions: {', '.join(self.checksum_extra_ext)}\n")
                        rf.write("\n### Reproduce (approx)\n")
                        rf.write("```bash\n" + " \\\n+  ".join(repro) + "\n```\n")
                except Exception:
                    pass
                log_msg("Manifest written.", phase="post")
            except Exception as e:
                self.progress.emit(f"Manifest write failed: {e}")

        # ensure total progress is shown as 100% at the end
        emit_total("cleanup", 100)
        self.finished.emit("\n".join(log), docker_success, clone_success)

    # ----- internal progress helpers -----
    def _run_wget_with_progress(self, wget_cmd, emit_total_cb) -> bool:
        """Run wget2 and emit progress like 'Cloning site: XX%' to the console."""
        try:
            proc = subprocess.Popen(
                wget_cmd,
                stdout=subprocess.DEVNULL,  # avoid blocking on stdout
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self._active_proc = proc
        except FileNotFoundError:
            self.progress.emit("Error: wget2 not found.")
            return False

        last_pct = -1
        last_rate = None
        last_rate_emit_time = 0.0
        import re, time as _time
        # Pattern capturing speed tokens (e.g., 123K/s, 1.2M/s, 450/s, 450B/s)
        speed_re = re.compile(r"(?P<val>\d+(?:\.\d+)?)(?P<unit>[KMG]?)(?:B?/s|/s)")
        try:
            stream = proc.stderr
            if stream is not None:
                for line in stream:
                    if self._stop_requested:
                        break
                    if not line:
                        continue
                    # Parse percentage like '  12%'
                    for token in line.split():
                        if token.endswith('%'):
                            try:
                                pct = int(token.rstrip('%'))
                            except ValueError:
                                continue
                            if 0 <= pct <= 100 and pct != last_pct:
                                last_pct = pct
                                self.progress.emit(f"Cloning site: {pct}%")
                                emit_total_cb("clone", pct)
                            break
                    # Extract current transfer rate if present; throttle UI updates
                    if 's' in line:  # cheap filter
                        m = speed_re.search(line)
                        if m:
                            unit = m.group('unit') or ''
                            val = m.group('val')
                            human_rate = f"{val}{unit}B/s" if unit else f"{val}B/s"
                            now = _time.time()
                            if human_rate != last_rate and (now - last_rate_emit_time) > 0.2:
                                last_rate = human_rate
                                last_rate_emit_time = now
                                self.bandwidth.emit(human_rate)
            if self._stop_requested:
                try:
                    proc.terminate()
                except Exception:
                    pass
            proc.wait()
        except Exception as e:
            self.progress.emit(f"Cloning error while reading progress: {e}")
        if self._stop_requested:
            self.progress.emit("Clone canceled.")
            return False
        if proc.returncode != 0:
            self.progress.emit("Error cloning site (wget2 exit code != 0).")
            return False
        if last_pct < 100:
            self.progress.emit("Cloning site: 100%")
            emit_total_cb("clone", 100)
        return True

    # ----- helper builders -----
    def _build_repro_command(self) -> list[str]:
        """Assemble an approximate reproduction command reflecting the clone options.
        Only includes non-default or enabled flags to keep it concise.
        """
        cmd = ["python cw2dt.py --headless",
               f"--url '{self.url}'",
               f"--dest '{self.save_path}'",
               f"--docker-name '{self.docker_name}'"]
        if self.prerender:
            cmd.append("--prerender")
            if self.prerender_max_pages != DEFAULT_PRERENDER_MAX_PAGES:
                cmd.append(f"--prerender-max-pages {self.prerender_max_pages}")
            if self.capture_api:
                cmd.append("--capture-api")
            if not self.rewrite_urls:
                cmd.append("--no-url-rewrite")
        if self.router_intercept:
            cmd.append("--router-intercept")
            if self.router_include_hash:
                cmd.append("--router-include-hash")
            if self.router_max_routes != DEFAULT_ROUTER_MAX_ROUTES:
                cmd.append(f"--router-max-routes {self.router_max_routes}")
            if self.router_settle_ms != DEFAULT_ROUTER_SETTLE_MS:
                cmd.append(f"--router-settle-ms {self.router_settle_ms}")
            if self.router_wait_selector:
                cmd.append(f"--router-wait-selector '{self.router_wait_selector}'")
            if self.router_allow:
                cmd.append(f"--router-allow {','.join(self.router_allow)}")
            if self.router_deny:
                cmd.append(f"--router-deny {','.join(self.router_deny)}")
            if self.router_quiet:
                cmd.append("--router-quiet")
        if self.disable_js:
            cmd.append("--disable-js")
        if self.size_cap:
            cmd.append(f"--size-cap {human_quota_suffix(self.size_cap)}")
        if self.throttle:
            cmd.append(f"--throttle {human_rate_suffix(self.throttle)}")
        if self.parallel_jobs > 1:
            cmd.append(f"--jobs {self.parallel_jobs}")
        if self.checksums:
            cmd.append("--checksums")
            if self.checksum_extra_ext:
                cmd.append(f"--checksum-ext {','.join(self.checksum_extra_ext)}")
        if self.no_manifest:
            cmd.append("--no-manifest")
        return cmd

    def _estimate_with_spider(self, url: str) -> int:
        """Run wget2 in spider mode to estimate number of URLs to fetch."""
        cmd = [
            "wget2", "--spider", "-e", "robots=off",
            "--recursive", "--no-parent",
            url
        ]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        except Exception:
            return 0
        seen = set()
        try:
            stream = proc.stdout
            if stream is None:
                proc.wait()
                return 0
            for line in stream:
                if not line:
                    continue
                line = line.strip()
                # Typical lines start with '--YYYY...' then a URL
                if line.startswith("--"):
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].startswith("http"):
                        seen.add(parts[1])
                        continue
                # wget2 can print 'URL:' tokens
                if "http://" in line or "https://" in line:
                    for token in line.split():
                        if token.startswith("http://") or token.startswith("https://"):
                            seen.add(token)
        finally:
            proc.wait()
        return len(seen)

    def _run_docker_build_with_progress(self, context_dir: str, image_tag: str, emit_total_cb) -> bool:
        """Run docker build and roughly emit percent based on 'Step X/Y'."""
        try:
            proc = subprocess.Popen(
                ["docker", "build", "-t", image_tag, context_dir],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self._active_proc = proc
        except FileNotFoundError:
            self.progress.emit("Error: docker not found.")
            return False

        import re
        step_re = re.compile(r"^Step\s+(\d+)\s*/\s*(\d+)")
        last_pct = -1
        lines = []
        try:
            stream = proc.stdout
            if stream is not None:
                for line in stream:
                    if self._stop_requested:
                        break
                    if not line:
                        continue
                    lines.append(line.rstrip())
                    m = step_re.search(line)
                    if m:
                        try:
                            cur = int(m.group(1)); total = int(m.group(2)) or 1
                            pct = max(0, min(100, int(cur * 100 / total)))
                            if pct != last_pct:
                                last_pct = pct
                                self.progress.emit(f"Docker build: {pct}% (Step {cur}/{total})")
                                emit_total_cb("build", pct)
                        except Exception:
                            pass
            if self._stop_requested:
                try:
                    proc.terminate()
                except Exception:
                    pass
            proc.wait()
        except Exception as e:
            self.progress.emit(f"Build error while reading output: {e}")
        if self._stop_requested:
            self.progress.emit("Docker build canceled.")
            return False
        if proc.returncode != 0:
            tail = "\n".join(lines[-10:])
            self.progress.emit(f"Docker build failed. Last output:\n{tail}")
            return False
        if last_pct < 100:
            self.progress.emit("Docker build: 100%")
            emit_total_cb("build", 100)
        return True

    def _cleanup_with_progress(self, output_folder: str, emit_total_cb, keep_rel_root: Optional[str] = None):
        """Delete build inputs with basic progress messages."""
        try:
            items = list(os.listdir(output_folder))
        except Exception as e:
            self.progress.emit(f"Cleanup listing failed: {e}")
            return
        total = len(items) if items else 1
        done = 0
        keep_dir = os.path.normpath(keep_rel_root or "")
        for item in items:
            path = os.path.join(output_folder, item)
            # Do not remove README files
            if item.startswith("README_"):
                continue
            # Preserve the downloaded site contents for resume/serve
            if keep_dir and (item == keep_dir.split(os.sep)[0]):
                continue
            # Only remove known build artifacts
            if item not in {"Dockerfile", "nginx.conf"} and not item.startswith(".folder.default."):
                continue
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.unlink(path)
            except Exception as e:
                self.progress.emit(f"Cleanup warning ({item}): {e}")
            done += 1
            pct = max(0, min(100, int(done * 100 / total)))
            self.progress.emit(f"Cleanup: {pct}% ({done}/{total})")
            emit_total_cb("cleanup", pct)

    def _strip_js_from_html(self, root_dir: str):
        import re
        script_re = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
        scanned = 0
        stripped = 0
        for base, _, files in os.walk(root_dir):
            for fn in files:
                if fn.lower().endswith((".html", ".htm")):
                    scanned += 1
                    p = os.path.join(base, fn)
                    try:
                        with open(p, "r", encoding="utf-8", errors="ignore") as f:
                            txt = f.read()
                        new_txt = script_re.sub("", txt)
                        if new_txt != txt:
                            with open(p, "w", encoding="utf-8") as f:
                                f.write(new_txt)
                            stripped += 1
                    except Exception:
                        continue
        return scanned, stripped

def build_light_css(scale: float = 1.0) -> str:
    sf = max(0.7, min(1.5, float(scale or 1.0)))
    fs_base = int(round(13 * sf))
    fs_title = int(round(14 * sf))
    fs_section = int(round(15 * sf))
    # Reduced rounding for inputs/buttons/card
    rad_inp = max(2, int(round(4 * sf)))
    pad_v = max(3, int(round(5 * sf)))
    pad_h = max(4, int(round(8 * sf)))
    rad_btn = max(3, int(round(6 * sf)))
    rad_card = max(4, int(round(6 * sf)))
    return f"""
QWidget {{ color: #1d2733; font-size: {fs_base}px; }}
QWidget {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                      stop:0 #f4f6f9, stop:1 #e7ebf1); }}
QLineEdit, QTextEdit, QSpinBox, QComboBox {{
    background-color: #ffffff;
    border: 1px solid #b9c4d1;
    border-radius: {rad_inp}px;
    padding: {pad_v}px {pad_h}px;
    color: #1d2733;
}}
QPushButton {{
    background-color: #2d6fd2;
    border: 1px solid #2d6fd2;
    border-radius: {rad_btn}px;
    padding: {pad_v+2}px {pad_h+2}px;
    color: #ffffff;
}}
QPushButton#primaryBtn {{ background-color: #1d5fbf; }}
QPushButton#ghostBtn {{ background-color: rgba(45,111,210,0.12); border:1px solid rgba(45,111,210,0.35); color:#1d5fbf; }}
QPushButton#dangerBtn {{ background-color: #d24c3b; border-color: #d24c3b; }}
QPushButton:disabled {{ background-color: #d4dbe3; color: #7a8896; border-color: #c2cbd5; }}
QLabel[role=\"title\"] {{ color: #2d3e50; font-size: {fs_title}px; font-weight: 500; }}
QLabel[role=\"section\"] {{ color: #1d5fbf; font-size: {fs_section}px; font-weight: 600; }}
QFrame#card {{ background-color: #ffffff; border-radius: {rad_card}px; border:1px solid #c2ccd6; }}
QFrame#divider {{ background-color: #ccd6e2; min-height:1px; max-height:1px; }}
QLabel#status {{ background-color: #f0f3f7; border:1px solid #ccd6e2; border-radius: 10px; padding:6px; color:#1d2733; }}
"""

class InstallerThread(QThread):
    progress = Signal(str)
    finished_ok = Signal(bool)

    def __init__(self, cmd):
        super().__init__()
        self.cmd = cmd

    def run(self):
        try:
            proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        except Exception as e:
            self.progress.emit(f"Installer start failed: {e}")
            self.finished_ok.emit(False)
            return
        lines: list[str] = []  # keep only last 50 lines
        try:
            stream = proc.stdout
            if stream is not None:
                for raw_line in stream:
                    if raw_line is None:
                        continue
                    line = raw_line.rstrip('\n')
                    if not line:
                        continue
                    lines.append(line)
                    if len(lines) > 50:
                        del lines[0:len(lines)-50]
                    self.progress.emit(line)
            proc.wait()
        except Exception as e:  # pragma: no cover - defensive
            self.progress.emit(f"Installer error: {e}")
        ok = (proc.returncode == 0)
        if not ok and lines:
            tail = "\n".join(lines[-10:])
            self.progress.emit(f"Install failed, last output:\n{tail}")
        self.finished_ok.emit(ok)

class DockerClonerGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Clone Website to Docker Tool")
        # sizing handled dynamically below

        # --- State ---
        self.container_id = None
        self.container_url = None
        self.container_start_time = None
        self.current_port = 8080              # host port
        self.current_container_port = 80      # container port (mapped)
        self.current_host_ip = "127.0.0.1"
        self.last_project_dir = None
        # Defaults for cloning behavior
        self.default_estimate_first = True
        try:
            _cores = os.cpu_count() or 4
        except Exception:
            _cores = 4
        self.default_parallel_jobs = min(16, max(4, int(_cores)))
        # Clone control state
        self.clone_thread = None
        self.last_clone_failed_or_canceled = False

        # Settings for persistence (geometry, recents)
        try:
            self.settings = QSettings("CloneWebsiteDockerTool", "CW2DT")
        except Exception:
            # Fallback: older PySide variant may prefer just organization
            try:
                self.settings = QSettings("CloneWebsiteDockerTool")  # type: ignore
            except Exception:
                self.settings = None
        # Automatic UI scale based on available screen size (no manual control)
        self.ui_scale = self._compute_auto_scale()
        # Use a lighter variant by default to improve readability (single theme only)
        self.setStyleSheet(build_light_css(self.ui_scale))

        # Outer layout
        root = QVBoxLayout(self)
        self.root_layout = root
        self._set_scaled_margins(root, 16, 16, 16, 16)
        root.setSpacing(int(14 * self.ui_scale))

        # Card
        self.card = QFrame()
        self.card.setObjectName("card")
        # Shadow removed for flatter appearance

        card_layout = QVBoxLayout(self.card)
        self._set_scaled_margins(card_layout, 18, 18, 18, 18)
        card_layout.setSpacing(int(12 * self.ui_scale))
        # Wrap in a scroll area so smaller screens can still access all controls
        self.scroll_area = QScrollArea(); self.scroll_area.setWidget(self.card); self.scroll_area.setWidgetResizable(True)
        try:
            self.scroll_area.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        except Exception:
            pass
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        # Main split: left = scroll area (controls), right = console panel
        self.right_panel = QFrame(); self.right_panel.setObjectName("rightPanel")
        try:
            # Ensure it paints an opaque background (prevents visual overlap artifacts)
            self.right_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        except Exception:
            pass
        # Prevent the console panel from collapsing past this width
        self.right_panel.setMinimumWidth(320)
        self.right_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.right_col = QVBoxLayout(self.right_panel); self.right_col.setContentsMargins(12,0,0,0); self.right_col.setSpacing(int(10 * self.ui_scale))

        # Use a fixed divider rather than a resizable splitter
        self.panes = QFrame()
        panes_layout = QHBoxLayout(self.panes)
        panes_layout.setContentsMargins(0, 0, 0, 0)
        panes_layout.setSpacing(0)
        panes_layout.addWidget(self.scroll_area)
        self.fixed_divider = QFrame(); self.fixed_divider.setObjectName("fixedDivider")
        self.fixed_divider.setFrameShape(QFrame.Shape.NoFrame)
        self.fixed_divider.setMinimumWidth(8); self.fixed_divider.setMaximumWidth(8)
        try:
            self.fixed_divider.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self.fixed_divider.setStyleSheet("#fixedDivider { background: rgba(255,255,255,0.06); }")
        except Exception:
            pass
        panes_layout.addWidget(self.fixed_divider)
        panes_layout.addWidget(self.right_panel)
        try:
            panes_layout.setStretch(0, 2)
            panes_layout.setStretch(2, 3)
        except Exception:
            pass
        root.addWidget(self.panes)

        # Set a firm minimum window width so panes never overlap
        self._update_min_window_width()
        # Keep the left panel reasonable; do not force full content width
        try:
            self.scroll_area.setMinimumWidth(280)
        except Exception:
            pass
        # Ensure the window cannot be shrunk smaller than the sum of pane minimums
        self._update_min_window_width()

        # Icons (top of panel)
        icon_row = QHBoxLayout(); icon_row.setContentsMargins(0, 0, 0, 6); icon_row.setSpacing(10)
        icon_row.addStretch(1)
        icon_row.addWidget(load_icon_label("web_logo.png",    size=60, alt_text="WEB"))
        icon_row.addSpacing(8)
        icon_row.addWidget(load_icon_label("arrow_right.png", size=48, alt_text="→"))
        icon_row.addSpacing(8)
        icon_row.addWidget(load_icon_label("docker_logo.png", size=60, alt_text="DOCKER"))
        icon_row.addStretch(1)
        card_layout.addLayout(icon_row)

    # (Advanced Mode toggle removed; sections manage their own collapsed state.)

        # ---------- DEPENDENCIES ----------
        self.deps_frame = QFrame(); deps = QHBoxLayout(self.deps_frame); deps.setContentsMargins(0,0,0,0)
        # Status-only labels (no action buttons here)
        self.dep_wget2_label = QLabel("")
        self.dep_docker_label = QLabel("")
        self.dep_bc3_label = QLabel("")
        deps.addWidget(self.dep_wget2_label); deps.addSpacing(12)
        deps.addWidget(self.dep_docker_label); deps.addSpacing(12)
        deps.addWidget(self.dep_bc3_label); deps.addStretch(1)
        card_layout.addWidget(self.deps_frame)

        # ---------- SOURCE ----------
        lbl_source = QLabel("Source"); lbl_source.setProperty("role", "section")
        card_layout.addWidget(lbl_source)
        card_layout.addWidget(divider())

        source_grid = QGridLayout(); source_grid.setHorizontalSpacing(10); source_grid.setVerticalSpacing(8)
        self.lbl_url  = QLabel("Website URL:"); self.lbl_url.setProperty("role", "title")
        from PySide6.QtWidgets import QComboBox as _QComboBox  # local alias to avoid confusion
        self.url_input = _QComboBox(); self.url_input.setEditable(True)
        try:
            le = self.url_input.lineEdit()
            if le is not None:
                le.setPlaceholderText("e.g., https://example.com")
        except Exception:
            pass
        source_grid.addWidget(self.lbl_url, 0, 0); source_grid.addWidget(self.url_input, 0, 1, 1, 2)

        self.lbl_dest = QLabel("Destination Folder:"); self.lbl_dest.setProperty("role", "title")
        dest_row = QHBoxLayout()
        self.save_path_display = QLineEdit(); self.save_path_display.setReadOnly(True)
        browse_btn = QPushButton("Browse"); browse_btn.setObjectName("ghostBtn"); browse_btn.clicked.connect(self.browse_folder)
        # Recent destinations menu
        from PySide6.QtWidgets import QMenu as _QMenu
        self.recent_dest_btn = QPushButton("Recent"); self.recent_dest_btn.setObjectName("ghostBtn")
        self.recent_dest_btn.setEnabled(True)
        def _populate_recent_menu():
            menu = _QMenu(self.recent_dest_btn)
            items = []
            try:
                if self.settings:
                    raw = self.settings.value('recent_dests', '', type=str) or ''
                    raw = str(raw)
                    items = [p for p in raw.split('\n') if p.strip()]
            except Exception:
                items = []
            if not items:
                act = menu.addAction('(none)')
                act.setEnabled(False)
            else:
                for p in items:
                    def make_set(path=p):
                        def _():
                            self.save_path_display.setText(path)
                            self._update_clone_button_state()
                        return _
                    menu.addAction(p, make_set())
            return menu
        def _show_recent_menu():
            try:
                menu = _populate_recent_menu()
                menu.exec(self.recent_dest_btn.mapToGlobal(self.recent_dest_btn.rect().bottomLeft()))
            except Exception:
                pass
        self.recent_dest_btn.clicked.connect(_show_recent_menu)
        dest_row.addWidget(self.save_path_display, 1); dest_row.addWidget(browse_btn, 0); dest_row.addWidget(self.recent_dest_btn, 0)
        source_grid.addWidget(self.lbl_dest, 1, 0); source_grid.addLayout(dest_row, 1, 1, 1, 2)
        card_layout.addLayout(source_grid)

        # Helper to bind enabling of widgets to a checkbox state (immediate apply + on change).
        # Keeps UI logic DRY versus many repeated lambda stateChanged connections.
        def _bind_enable(chk: QCheckBox, *widgets):
            def _apply():
                on = chk.isChecked()
                for w in widgets:
                    try:
                        w.setEnabled(on)
                    except Exception:
                        pass
            chk.stateChanged.connect(_apply)
            _apply()
        self._bind_enable = _bind_enable  # store for later use

        # ---------- BUILD (collapsible) ----------
        build_grid = QGridLayout(); build_grid.setHorizontalSpacing(10); build_grid.setVerticalSpacing(8)
        self.build_checkbox = QCheckBox("Build Docker image after clone")
        build_grid.addWidget(self.build_checkbox, 0, 0, 1, 3)

        self.lbl_img = QLabel("Docker Image Name:"); self.lbl_img.setProperty("role", "title")
        self.docker_name_input = QLineEdit(); self.docker_name_input.setPlaceholderText("e.g., mysite"); self.docker_name_input.textChanged.connect(self.refresh_run_buttons)
        build_grid.addWidget(self.lbl_img, 1, 0); build_grid.addWidget(self.docker_name_input, 1, 1, 1, 2)

        self.size_frame = QFrame(); sz = QHBoxLayout(self.size_frame); sz.setContentsMargins(0,0,0,0)
        self.size_cap_checkbox = QCheckBox("Limit download size")
        self.size_cap_value = QSpinBox(); self.size_cap_value.setRange(1,1_000_000); self.size_cap_value.setValue(200)
        self.size_cap_unit = QComboBox(); self.size_cap_unit.addItems(["MB","GB","TB"])
        self.size_cap_value.setEnabled(False); self.size_cap_unit.setEnabled(False)
        # (Enable logic unified later via self._bind_enable)
        sz.addWidget(self.size_cap_checkbox); sz.addSpacing(6); sz.addWidget(self.size_cap_value); sz.addWidget(self.size_cap_unit)
        build_grid.addWidget(self.size_frame, 2, 0, 1, 3)

        self.throttle_frame = QFrame(); th = QHBoxLayout(self.throttle_frame); th.setContentsMargins(0,0,0,0)
        self.throttle_checkbox = QCheckBox("Throttle download speed")
        self.throttle_value = QSpinBox(); self.throttle_value.setRange(1,1_000_000); self.throttle_value.setValue(1024)
        self.throttle_unit = QComboBox(); self.throttle_unit.addItems(["KB/s","MB/s"])
        self.throttle_value.setEnabled(False); self.throttle_unit.setEnabled(False)
        # (Enable logic unified later via self._bind_enable)
        th.addWidget(self.throttle_checkbox); th.addSpacing(6); th.addWidget(self.throttle_value); th.addWidget(self.throttle_unit)
        build_grid.addWidget(self.throttle_frame, 3, 0, 1, 3)

        build_container = QWidget(); build_container.setLayout(build_grid)
        self.build_section = CollapsibleSection("Build", start_collapsed=False)
        self.build_section.setContentLayout(build_grid)
        card_layout.addWidget(self.build_section)

        # ---------- AUTH & SESSIONS ----------
        auth_layout = QGridLayout(); auth_layout.setHorizontalSpacing(10); auth_layout.setVerticalSpacing(6)
        self.auth_checkbox = QCheckBox("HTTP authentication")
        self.auth_checkbox.setToolTip("Use basic auth (credentials passed to wget2; consider netrc for higher security).")
        self.auth_user_input = QLineEdit(); self.auth_user_input.setPlaceholderText("User"); self.auth_user_input.setEnabled(False)
        self.auth_pass_input = QLineEdit(); self.auth_pass_input.setPlaceholderText("Password"); self.auth_pass_input.setEchoMode(QLineEdit.EchoMode.Password); self.auth_pass_input.setEnabled(False)
        # (Enable logic unified later via self._bind_enable)
        auth_layout.addWidget(self.auth_checkbox, 0,0)
        auth_layout.addWidget(self.auth_user_input,0,1)
        auth_layout.addWidget(self.auth_pass_input,0,2)
        # Cookies
        self.scan_cookies_btn = QPushButton("Scan Cookies"); self.scan_cookies_btn.setObjectName("ghostBtn"); self.scan_cookies_btn.clicked.connect(self.scan_browser_cookies)
        self.use_cookies_checkbox = QCheckBox("Use imported cookies"); self.use_cookies_checkbox.setEnabled(False)
        self.cookies_status = QLabel("No cookies imported")
        cookie_row = QHBoxLayout(); cookie_row.addWidget(self.scan_cookies_btn); cookie_row.addWidget(self.use_cookies_checkbox); cookie_row.addSpacing(6); cookie_row.addWidget(self.cookies_status); cookie_row.addStretch(1)
        auth_layout.addLayout(cookie_row,1,0,1,3)
        self.auth_section = CollapsibleSection("Auth & Sessions", start_collapsed=True)
        self.auth_section.setContentLayout(auth_layout)
        card_layout.addWidget(self.auth_section)

        # ---------- PERFORMANCE & LIMITS ----------
        perf_layout = QGridLayout(); perf_layout.setHorizontalSpacing(10); perf_layout.setVerticalSpacing(6)
        self.estimate_checkbox = QCheckBox("Estimate before clone"); self.estimate_checkbox.setChecked(True)
        self.parallel_checkbox = QCheckBox("Parallel downloads"); self.parallel_checkbox.setChecked(True)
        self.parallel_jobs_label = QLabel("Jobs:")
        self.parallel_jobs_input = QSpinBox(); self.parallel_jobs_input.setRange(1,64); self.parallel_jobs_input.setValue(self.default_parallel_jobs); self.parallel_jobs_input.setEnabled(True)
    # (Enable logic unified later via self._bind_enable)
        self.disable_js_checkbox = QCheckBox("Disable JavaScript post-clone")
        # Reuse existing size/throttle frames from build section visually by duplicating minimal controls (no side-effects)
        perf_layout.addWidget(self.estimate_checkbox,0,0)
        perf_layout.addWidget(self.parallel_checkbox,0,1)
        perf_layout.addWidget(self.parallel_jobs_label,0,2)
        perf_layout.addWidget(self.parallel_jobs_input,0,3)
        perf_layout.addWidget(self.disable_js_checkbox,1,0,1,2)
        self.perf_section = CollapsibleSection("Performance & Limits", start_collapsed=True)
        self.perf_section.setContentLayout(perf_layout)
        card_layout.addWidget(self.perf_section)

        # ---------- DYNAMIC RENDERING ----------
        from PySide6.QtWidgets import QSpinBox as _QSpinBox
        dyn_layout = QGridLayout(); dyn_layout.setHorizontalSpacing(10); dyn_layout.setVerticalSpacing(6)
        self.prerender_checkbox = QCheckBox("Enable prerender (Playwright)")
        self.prerender_pages_spin = _QSpinBox(); self.prerender_pages_spin.setRange(1,500); self.prerender_pages_spin.setValue(40); self.prerender_pages_spin.setEnabled(False)
        self.capture_api_checkbox = QCheckBox("Capture API JSON"); self.capture_api_checkbox.setEnabled(False)
        self.no_rewrite_checkbox = QCheckBox("Keep absolute URLs"); self.no_rewrite_checkbox.setEnabled(False)
        self.hook_script_btn = QPushButton("Select Hook Script"); self.hook_script_btn.setObjectName("ghostBtn")
        self.hook_script_path = None
        def pick_hook():
            path, _ = QFileDialog.getOpenFileName(self, "Select Hook Script", "", "Python Files (*.py)")
            if path:
                self.hook_script_path = path; self.console.append(f"Hook script set: {path}")
        self.hook_script_btn.clicked.connect(pick_hook)
        # (Enable logic unified later via self._bind_enable)
        dyn_layout.addWidget(self.prerender_checkbox,0,0,1,2)
        dyn_layout.addWidget(QLabel("Max pages:"),1,0)
        dyn_layout.addWidget(self.prerender_pages_spin,1,1)
        dyn_layout.addWidget(self.capture_api_checkbox,1,2)
        dyn_layout.addWidget(self.no_rewrite_checkbox,1,3)
        dyn_layout.addWidget(self.hook_script_btn,2,0,1,2)
        from PySide6.QtWidgets import QToolButton as _QToolButton
        self.dynamic_section = CollapsibleSection("Dynamic Rendering", start_collapsed=True)
        try:
            dyn_help_btn = _QToolButton(); dyn_help_btn.setText("?")
            dyn_help_btn.setObjectName("ghostBtn")
            dyn_help_btn.setToolTip("Prerender pages with a headless browser to capture dynamic content.")
            def _dyn_help():
                QMessageBox.information(self, "Dynamic Rendering Help", (
                    "Prerender uses Playwright to execute JavaScript and capture rendered HTML.\n"
                    "Options:\n"
                    " - Max pages: limit prerendered pages\n"
                    " - Capture API JSON: save JSON responses\n"
                    " - Keep absolute URLs: do not rewrite links\n"
                    " - Hook Script: custom Python executed after each prerender."))
            dyn_help_btn.clicked.connect(_dyn_help)
            hl = self.dynamic_section.header.layout() if hasattr(self.dynamic_section.header, 'layout') else None
            if hl:
                hl.addWidget(dyn_help_btn)
        except Exception:
            pass
        self.dynamic_section.setContentLayout(dyn_layout)
        card_layout.addWidget(self.dynamic_section)

        # ---------- SPA ROUTER ----------
        from PySide6.QtWidgets import QSpinBox as _QSpinBox2
        router_layout = QGridLayout(); router_layout.setHorizontalSpacing(10); router_layout.setVerticalSpacing(6)
        self.router_intercept_checkbox = QCheckBox("Intercept router")
        self.router_intercept_checkbox.setEnabled(False)
        # (Enable logic unified later via self._bind_enable)
        self.router_hash_checkbox = QCheckBox("Include #hash"); self.router_hash_checkbox.setEnabled(False)
        # (Enable logic unified later via self._bind_enable)
        self.router_max_routes_spin = _QSpinBox2(); self.router_max_routes_spin.setRange(10,5000); self.router_max_routes_spin.setValue(200); self.router_max_routes_spin.setEnabled(False)
        self.router_settle_spin = _QSpinBox2(); self.router_settle_spin.setRange(0,5000); self.router_settle_spin.setValue(350); self.router_settle_spin.setSuffix(" ms"); self.router_settle_spin.setEnabled(False)
        self.router_wait_selector_edit = QLineEdit(); self.router_wait_selector_edit.setPlaceholderText("Wait selector (optional)"); self.router_wait_selector_edit.setEnabled(False)
        # (Enable logic unified later via self._bind_enable)
        self.router_allow_edit = QLineEdit(); self.router_allow_edit.setPlaceholderText("Allow regex list"); self.router_allow_edit.setEnabled(False)
        self.router_deny_edit = QLineEdit(); self.router_deny_edit.setPlaceholderText("Deny regex list"); self.router_deny_edit.setEnabled(False)
        # (Enable logic unified later via self._bind_enable)
        self.router_quiet_checkbox = QCheckBox("Quiet logging"); self.router_quiet_checkbox.setEnabled(False)
        # (Enable logic unified later via self._bind_enable)
        router_layout.addWidget(self.router_intercept_checkbox,0,0)
        router_layout.addWidget(self.router_hash_checkbox,0,1)
        router_layout.addWidget(QLabel("Max routes:"),1,0)
        router_layout.addWidget(self.router_max_routes_spin,1,1)
        router_layout.addWidget(QLabel("Settle:"),1,2)
        router_layout.addWidget(self.router_settle_spin,1,3)
        router_layout.addWidget(self.router_wait_selector_edit,2,0,1,4)
        router_layout.addWidget(QLabel("Allow patterns:"),3,0)
        router_layout.addWidget(self.router_allow_edit,3,1,1,3)
        router_layout.addWidget(QLabel("Deny patterns:"),4,0)
        router_layout.addWidget(self.router_deny_edit,4,1,1,3)
        router_layout.addWidget(self.router_quiet_checkbox,5,0)
        self.router_section = CollapsibleSection("SPA Router", start_collapsed=True)
        try:
            router_help_btn = _QToolButton(); router_help_btn.setText("?")
            router_help_btn.setObjectName("ghostBtn")
            router_help_btn.setToolTip("Intercept client-side router navigation to enumerate routes.")
            def _router_help():
                QMessageBox.information(self, "SPA Router Help", (
                    "Intercept client-side navigation (history/hash) to enumerate routes during prerender.\n"
                    "Controls:\n"
                    " - Include #hash: treat hash fragments as unique\n"
                    " - Max routes: maximum discovered routes\n"
                    " - Settle: ms to wait after navigation before capture\n"
                    " - Allow/Deny: regex filters (comma separated)\n"
                    " - Quiet logging: reduce console noise."))
            router_help_btn.clicked.connect(_router_help)
            hl2 = self.router_section.header.layout() if hasattr(self.router_section.header, 'layout') else None
            if hl2:
                hl2.addWidget(router_help_btn)
        except Exception:
            pass
        self.router_section.setContentLayout(router_layout)
        card_layout.addWidget(self.router_section)
        # Unified enable/disable bindings (after all related widgets created)
        self._bind_enable(self.size_cap_checkbox, self.size_cap_value, self.size_cap_unit)
        self._bind_enable(self.throttle_checkbox, self.throttle_value, self.throttle_unit)
        self._bind_enable(self.auth_checkbox, self.auth_user_input, self.auth_pass_input)
        self._bind_enable(self.parallel_checkbox, self.parallel_jobs_input)
        self._bind_enable(self.prerender_checkbox,
                          self.prerender_pages_spin,
                          self.capture_api_checkbox,
                          self.no_rewrite_checkbox,
                          self.router_intercept_checkbox)
        self._bind_enable(self.router_intercept_checkbox,
                          self.router_hash_checkbox,
                          self.router_max_routes_spin,
                          self.router_settle_spin,
                          self.router_wait_selector_edit,
                          self.router_allow_edit,
                          self.router_deny_edit,
                          self.router_quiet_checkbox)

        # ---------- INTEGRITY & ARTIFACTS ----------
        integ_layout = QGridLayout(); integ_layout.setHorizontalSpacing(10); integ_layout.setVerticalSpacing(6)
        self.checksums_checkbox = QCheckBox("Generate checksums")
        self.skip_manifest_checkbox = QCheckBox("Skip manifest")
        self.verify_checksums_checkbox = QCheckBox("Verify after clone")
        self.verify_checksums_checkbox.setToolTip("After clone completes and checksums manifest is written, verify all recorded hashes.")
        self.verify_checksums_checkbox.setEnabled(True)
        self.verify_fast_checkbox = QCheckBox("Fast verify (skip missing)")
        self.verify_fast_checkbox.setToolTip("If enabled, missing files are reported quickly without hashing attempts (passes --fast-missing).")
        self.verify_fast_checkbox.setChecked(True)
        self.verify_fast_checkbox.setEnabled(False)
        self.checksum_extra_edit = QLineEdit(); self.checksum_extra_edit.setPlaceholderText("Extra checksum extensions (e.g. css,js)")
        integ_layout.addWidget(self.checksums_checkbox,0,0)
        integ_layout.addWidget(self.skip_manifest_checkbox,0,1)
        integ_layout.addWidget(self.verify_checksums_checkbox,0,2)
        integ_layout.addWidget(self.verify_fast_checkbox,0,3)
        integ_layout.addWidget(self.checksum_extra_edit,1,0,1,4)
        self.integrity_section = CollapsibleSection("Integrity & Artifacts", start_collapsed=True)
        self.integrity_section.setContentLayout(integ_layout)
        card_layout.addWidget(self.integrity_section)

        run_grid = QGridLayout(); run_grid.setHorizontalSpacing(10); run_grid.setVerticalSpacing(8)

        # Bind IP + Host Port + Container Port row(s)
        ip_row = QHBoxLayout()
        self.lbl_bind_ip = QLabel("Bind IP:"); self.lbl_bind_ip.setProperty("role", "title")
        self.bind_ip_input = QLineEdit(); self.bind_ip_input.setPlaceholderText("e.g., 127.0.0.1, 0.0.0.0, or your LAN IP"); self.bind_ip_input.setText("127.0.0.1")
        detect_btn = QPushButton("Detect LAN IP"); detect_btn.setObjectName("ghostBtn"); detect_btn.clicked.connect(self.fill_detected_ip)
        ip_row.addWidget(self.lbl_bind_ip); ip_row.addSpacing(6); ip_row.addWidget(self.bind_ip_input, 2); ip_row.addSpacing(10); ip_row.addWidget(detect_btn, 0)

        host_port_row = QHBoxLayout()
        self.lbl_port = QLabel("Host Port:"); self.lbl_port.setProperty("role", "title")
        self.port_input = QSpinBox(); self.port_input.setRange(1,65535); self.port_input.setValue(8080)
        host_port_row.addWidget(self.lbl_port); host_port_row.addSpacing(6); host_port_row.addWidget(self.port_input); host_port_row.addStretch(1)

        cont_port_row = QHBoxLayout()
        self.lbl_cport = QLabel("Container Port:"); self.lbl_cport.setProperty("role", "title")
        self.cport_input = QSpinBox(); self.cport_input.setRange(1,65535); self.cport_input.setValue(80)
        cont_port_row.addWidget(self.lbl_cport); cont_port_row.addSpacing(6); cont_port_row.addWidget(self.cport_input); cont_port_row.addStretch(1)

        run_grid.addLayout(ip_row,        0, 0, 1, 3)
        run_grid.addLayout(host_port_row, 1, 0, 1, 3)
        run_grid.addLayout(cont_port_row, 2, 0, 1, 3)

        # Actions row (kept outside the collapsible Run section)
        actions_row = QHBoxLayout()
        self.clone_btn = QPushButton("Clone & Prepare"); self.clone_btn.setObjectName("primaryBtn"); self.clone_btn.clicked.connect(self.start_clone)
        actions_row.addWidget(self.clone_btn)

        self.cancel_clone_btn = QPushButton("Cancel Clone"); self.cancel_clone_btn.setObjectName("dangerBtn"); self.cancel_clone_btn.setEnabled(False)
        self.cancel_clone_btn.clicked.connect(self.cancel_clone)
        actions_row.addWidget(self.cancel_clone_btn)

        self.resume_btn = QPushButton("Resume Clone"); self.resume_btn.setObjectName("ghostBtn"); self.resume_btn.setEnabled(False)
        self.resume_btn.setToolTip("Resume uses existing files and continues the mirror.")
        self.resume_btn.clicked.connect(self.start_clone)
        actions_row.addWidget(self.resume_btn)

        self.run_created_btn = QPushButton("Run Created Container"); self.run_created_btn.setObjectName("primaryBtn")
        self.run_created_btn.setEnabled(False)
        if not docker_available():
            self.run_created_btn.setToolTip(f"Docker not found. Install:\n{docker_install_instructions()}")
        self.run_created_btn.clicked.connect(self.run_created_container)
        actions_row.addWidget(self.run_created_btn)

        self.run_folder_btn = QPushButton("Serve From Folder (no build)"); self.run_folder_btn.setObjectName("primaryBtn")
        self.run_folder_btn.setEnabled(False)
        if not docker_available():
            self.run_folder_btn.setToolTip(f"Docker not found. Install:\n{docker_install_instructions()}")
        self.run_folder_btn.clicked.connect(self.run_from_folder)
        actions_row.addWidget(self.run_folder_btn)

        self.stop_btn = QPushButton("Stop Container"); self.stop_btn.setObjectName("dangerBtn")
        self.stop_btn.setEnabled(False); self.stop_btn.clicked.connect(self.stop_container)
        actions_row.addWidget(self.stop_btn)

        # Open Folder / platform-specific label (disabled until a project directory exists)
        _open_label = "Reveal in Finder" if sys.platform.startswith("darwin") else "Open Folder"
        self.open_folder_btn = QPushButton(_open_label); self.open_folder_btn.setObjectName("ghostBtn")
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self.open_project_folder)
        actions_row.addWidget(self.open_folder_btn)

        # Show a single button to trigger the dependencies dialog (only when something is missing)
        self.deps_dialog_btn = QPushButton("Fix Dependencies…"); self.deps_dialog_btn.setObjectName("ghostBtn")
        self.deps_dialog_btn.setVisible(False)
        self.deps_dialog_btn.clicked.connect(self.show_dependencies_dialog)
        actions_row.addWidget(self.deps_dialog_btn)
        actions_row.addStretch(1)

        # URL tools
        url_tools = QHBoxLayout()
        self.copy_url_btn = QPushButton("Copy URL"); self.copy_url_btn.setObjectName("ghostBtn"); self.copy_url_btn.setEnabled(False); self.copy_url_btn.clicked.connect(self.copy_url)
        self.open_url_btn = QPushButton("Open in Browser"); self.open_url_btn.setObjectName("ghostBtn"); self.open_url_btn.setEnabled(False); self.open_url_btn.clicked.connect(self.open_in_browser)
        url_tools.addWidget(self.copy_url_btn); url_tools.addWidget(self.open_url_btn); url_tools.addStretch(1)
        run_grid.addLayout(url_tools, 3, 0, 1, 3)
        self.run_section = CollapsibleSection("Run", start_collapsed=False)
        self.run_section.setContentLayout(run_grid)
        card_layout.addWidget(self.run_section)
        card_layout.addLayout(actions_row)

        # Console (right side)
        t = QLabel("Console Log:"); t.setProperty("role", "title")
        self.right_col.addWidget(t)
        self.resuming_label = QLabel("")
        self.resuming_label.setVisible(False); self.right_col.addWidget(self.resuming_label)
        self.console = QTextEdit(); self.console.setReadOnly(True); self.console.setMinimumHeight(260); self.console.setMinimumWidth(320)
        try:
            # Remove inner frame to avoid visual border conflicting with the splitter handle
            self.console.setFrameShape(QFrame.Shape.NoFrame)
            self.console.setLineWidth(0)
        except Exception:
            pass
        self.console.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.right_col.addWidget(self.console, 1)
        # Export / Clear log button row
        export_row = QHBoxLayout()
        self.save_log_btn = QPushButton("Save Log…"); self.save_log_btn.setObjectName("ghostBtn"); self.save_log_btn.clicked.connect(self.save_console_log)
        self.clear_log_btn = QPushButton("Clear Log"); self.clear_log_btn.setObjectName("ghostBtn"); self.clear_log_btn.clicked.connect(self.clear_console_log)
        export_row.addWidget(self.save_log_btn)
        export_row.addWidget(self.clear_log_btn)
        export_row.addStretch(1)
        self.right_col.addLayout(export_row)

        # Total progress (compact line)
        # (status bar carries total progress during tasks)

        # Divider above status bar
        root.addWidget(divider())
        # Thin progress bar (overall)
        from PySide6.QtWidgets import QProgressBar as _QProgressBar
        self.total_progress_bar = _QProgressBar()
        try:
            self.total_progress_bar.setRange(0,100)
            self.total_progress_bar.setValue(0)
            self.total_progress_bar.setTextVisible(False)
            self.total_progress_bar.setFixedHeight(6)
            self.total_progress_bar.setStyleSheet("QProgressBar{background:#d9e1ea;border-radius:3px;} QProgressBar::chunk{background:#2d6fd2;border-radius:3px;}")
        except Exception:
            pass
        root.addWidget(self.total_progress_bar)
        # Status pill (bottom spanning)
        self.status_label = QLabel("No container running"); self.status_label.setObjectName("status"); self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Fixed vertical size, stretch horizontally
        try:
            h = max(28, int(34 * self.ui_scale))
        except Exception:
            h = 34
        self.status_label.setMinimumHeight(h)
        self.status_label.setMaximumHeight(h)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # Shadow removed
        root.addWidget(self.status_label)
        # Verification status badge (hidden until a verification runs)
        self.verify_status_label = QLabel("")
        self.verify_status_label.setVisible(False)
        self.verify_status_label.setObjectName("verifyStatus")
        root.addWidget(self.verify_status_label)
        # Base status text used for appending progress
        self._status_base_text = "No container running"

        # timers & init
        self.status_timer = QTimer(); self.status_timer.timeout.connect(self.check_container_status); self.status_timer.start(3000)
        # (Advanced sections previously tracked for a toggle; feature removed)
        self._align_label_column()
        self.refresh_run_buttons()
        # Load previous window geometry if available, then finalize sizing
        self._geometry_restored = self._load_window_settings()
        self._finalize_sizing()
        self.refresh_deps_panel()
        # After show, check deps and gate features without popups
        try:
            QTimer.singleShot(0, self.run_dependency_dialog_if_needed)
        except Exception:
            pass
        # Load recents after settings available
        self._load_recent_urls()
        # Ensure left pane minimum width fits all content horizontally
        self._update_left_min_width()
        # Hook verification enable logic
        try:
            self.verify_checksums_checkbox.stateChanged.connect(self._update_verify_state)
            self.checksums_checkbox.stateChanged.connect(self._update_verify_state)
            self.skip_manifest_checkbox.stateChanged.connect(self._update_verify_state)
        except Exception:
            pass
        self._update_verify_state()
        # Install live validation & load recent destination, hide progress bar initially
        try:
            self._install_live_validation()
        except Exception:
            pass
        try:
            self._load_recent_dests()
        except Exception:
            pass
        try:
            if hasattr(self, 'total_progress_bar'):
                self.total_progress_bar.setVisible(False)
        except Exception:
            pass

    def _set_scaled_margins(self, layout: QLayout | None, left, top, right, bottom):
        if layout is None:
            return
        s = self.ui_scale
        layout.setContentsMargins(int(left*s), int(top*s), int(right*s), int(bottom*s))

    def _update_verify_state(self):
        """Enable/disable verify controls based on checksum + manifest settings."""
        try:
            checksums_on = self.checksums_checkbox.isChecked()
            skip_manifest = self.skip_manifest_checkbox.isChecked()
            allow_verify = checksums_on and not skip_manifest
            self.verify_checksums_checkbox.setEnabled(allow_verify)
            if not allow_verify:
                self.verify_checksums_checkbox.setChecked(False)
            fast_enabled = allow_verify and self.verify_checksums_checkbox.isChecked()
            self.verify_fast_checkbox.setEnabled(fast_enabled)
            if not fast_enabled:
                self.verify_fast_checkbox.setChecked(True)
            if not self.verify_checksums_checkbox.isChecked():
                self.verify_status_label.setVisible(False)
        except Exception:
            pass

    def clear_console_log(self):
        try:
            self.console.clear()
        except Exception:
            pass

    def save_console_log(self):
        """Save the current console log to a user-chosen file."""
        try:
            text = self.console.toPlainText()
            if not text.strip():
                QMessageBox.information(self, "Save Log", "Console log is empty.")
                return
            path, _ = QFileDialog.getSaveFileName(self, "Save Log", "clone_log.txt", "Text Files (*.txt)")
            if not path:
                return
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
            QMessageBox.information(self, "Save Log", f"Log saved to: {path}")
        except Exception as e:
            try:
                QMessageBox.warning(self, "Save Log", f"Failed to save log: {e}")
            except Exception:
                pass

    def open_project_folder(self):
        """Open the most recent project directory in the system file manager.

        Handles macOS, Windows, and Linux; shows an informational dialog if the path
        is not yet available and a warning dialog if invocation fails.
        """
        try:
            path = self.last_project_dir
            if not path or not os.path.isdir(path):
                QMessageBox.information(self, "Open Folder", "No project folder available yet.")
                return
            if sys.platform.startswith("darwin"):
                subprocess.run(["open", path])
            elif os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", path])
        except Exception as e:
            try:
                QMessageBox.warning(self, "Open Folder", f"Failed to open: {e}")
            except Exception:
                pass

    def _update_left_min_width(self):
        try:
            self.card.adjustSize()
            min_left = self.card.sizeHint().width() + int(24 * self.ui_scale)
            # Cap the left pane minimum so the console retains space;
            # overall window minimum prevents overlap.
            capped = max(280, min_left)
            self.scroll_area.setMinimumWidth(capped)
        except Exception:
            pass

    def _update_min_window_width(self):
        """Ensure the main window cannot be resized smaller than both pane minimums.
        Keeps the console’s left edge pinned by preventing layout compression/overlap.
        """
        try:
            left_min = int(self.scroll_area.minimumWidth()) if hasattr(self, 'scroll_area') else 0
            right_min = int(self.right_panel.minimumWidth()) if hasattr(self, 'right_panel') else 0
            divider_w = 0
            try:
                fd = getattr(self, 'fixed_divider', None)
                divider_w = int(fd.minimumWidth()) if fd is not None else 0
            except Exception:
                divider_w = 0
            # Include outer layout margins
            outer_lr = 0
            try:
                m = self.root_layout.contentsMargins()
                outer_lr = int(m.left() + m.right())
            except Exception:
                outer_lr = 0
            safety = int(12 * getattr(self, 'ui_scale', 1.0))
            total_min = max(100, left_min + divider_w + right_min + outer_lr + safety)
            self.setMinimumWidth(total_min)
            # Also ensure the inner panes container honors the minimum sum
            try:
                if hasattr(self, 'panes') and self.panes is not None:
                    self.panes.setMinimumWidth(left_min + divider_w + right_min)
            except Exception:
                pass
        except Exception:
            pass

    def _compute_auto_scale(self) -> float:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if not screen:
            return 1.0
        avail = screen.availableGeometry()
        # Target a base design of ~1280x900, scale down if smaller
        try:
            rw = avail.width() / 1280.0
            rh = avail.height() / 900.0
            scale = max(0.85, min(1.0, min(rw, rh)))
        except Exception:
            scale = 1.0
        return scale

    def apply_ui_scale(self, scale: float):
        try:
            self.ui_scale = max(0.7, min(1.5, float(scale)))
        except Exception:
            self.ui_scale = 1.0
        # Reapply stylesheet
        self.setStyleSheet(build_light_css(self.ui_scale))
        # Update key layout paddings
        root = self.layout()
        if root is not None:
            self._set_scaled_margins(root, 16, 16, 16, 16)
            root.setSpacing(int(14 * self.ui_scale))
        # Card layout margins
        if hasattr(self, 'card'):
            card_layout = self.card.layout()
            if card_layout is not None:
                self._set_scaled_margins(card_layout, 18, 18, 18, 18)
                card_layout.setSpacing(int(12 * self.ui_scale))
        # Realign fixed width labels to new font metrics
        try:
            self._align_label_column()
        except Exception:
            pass
        self._finalize_sizing()

    # ----- screen/scale monitoring -----
    def showEvent(self, event):
        super().showEvent(event)
        try:
            self._setup_screen_monitoring()
        except Exception:
            pass
        # Re-run sizing after the window is visible so frame metrics are accurate
        try:
            QTimer.singleShot(0, self._finalize_sizing)
        except Exception:
            pass

    def _setup_screen_monitoring(self):
        # Track current screen and react to changes in resolution/DPI
        try:
            self._scale_debounce = getattr(self, '_scale_debounce', None) or QTimer(self)
            self._scale_debounce.setSingleShot(True)
            self._scale_debounce.setInterval(200)
            self._scale_debounce.timeout.connect(self._refresh_auto_scale)
        except Exception:
            pass
        try:
            win = self.windowHandle()
            if win is not None:
                win.screenChanged.connect(self._on_screen_changed)
        except Exception:
            pass
        self._bound_screen = None
        self._bind_to_screen(self.screen() or QGuiApplication.primaryScreen())

    def _on_screen_changed(self, screen):
        self._bind_to_screen(screen)
        if hasattr(self, '_scale_debounce'):
            self._scale_debounce.start()

    def _bind_to_screen(self, screen):
        try:
            # disconnect previous
            if self._bound_screen is not None:
                try:
                    self._bound_screen.geometryChanged.disconnect(self._on_screen_metrics_changed)
                except Exception:
                    pass
                try:
                    self._bound_screen.availableGeometryChanged.disconnect(self._on_screen_metrics_changed)
                except Exception:
                    pass
                try:
                    self._bound_screen.logicalDotsPerInchChanged.disconnect(self._on_screen_metrics_changed)
                except Exception:
                    pass
        except Exception:
            pass
        self._bound_screen = screen
        if screen is None:
            return
        # connect new
        try:
            screen.geometryChanged.connect(self._on_screen_metrics_changed)
        except Exception:
            pass
        try:
            screen.availableGeometryChanged.connect(self._on_screen_metrics_changed)
        except Exception:
            pass
        try:
            screen.logicalDotsPerInchChanged.connect(self._on_screen_metrics_changed)
        except Exception:
            pass

    def _on_screen_metrics_changed(self, *args, **kwargs):
        if hasattr(self, '_scale_debounce'):
            self._scale_debounce.start()

    def _refresh_auto_scale(self):
        try:
            new_scale = self._compute_auto_scale()
        except Exception:
            new_scale = self.ui_scale
        # Only apply if change is meaningful (>2%)
        try:
            if abs(new_scale - self.ui_scale) > 0.02:
                self.apply_ui_scale(new_scale)
            else:
                # Still ensure sizing fits screen
                self._finalize_sizing()
        except Exception:
            pass
    # ----- live validation / destinations persistence -----
    def _install_live_validation(self):
        try:
            if hasattr(self.url_input, 'lineEdit'):
                le = self.url_input.lineEdit()
                if le:
                    le.textChanged.connect(self._update_clone_button_state)
        except Exception:
            pass
        for w_name in ('bind_ip_input','docker_name_input'):
            try:
                w = getattr(self, w_name, None)
                if w:
                    w.textChanged.connect(self._update_clone_button_state)
            except Exception:
                pass
        try:
            self.build_checkbox.stateChanged.connect(self._update_clone_button_state)
        except Exception:
            pass
        self._update_clone_button_state()

    def _collect_validation_errors(self):
        try:
            try:
                url = self.url_input.currentText().strip()
            except Exception:
                url = ''
            save_path = self.save_path_display.text().strip()
            ip_text = normalize_ip(self.bind_ip_input.text())
            docker_name = self.docker_name_input.text().strip()
            build_on = self.build_checkbox.isChecked()
            return validate_required_fields(url, save_path, ip_text, build_on, docker_name)
        except Exception:
            return []

    def _update_clone_button_state(self):
        errs = self._collect_validation_errors()
        disable = bool(errs) or bool(self.clone_thread and self.clone_thread.isRunning())
        try:
            self.clone_btn.setEnabled(not disable)
            self.clone_btn.setToolTip("Cannot start:\n - " + "\n - ".join(errs) if errs else "")
        except Exception:
            pass

    def _remember_recent_dest(self, path: str):
        if not path or not self.settings:
            return
        try:
            stored_raw = self.settings.value('recent_dests', '', type=str)
            stored = str(stored_raw) if stored_raw is not None else ''
            items = [p for p in stored.split('\n') if isinstance(p, str) and p.strip()]
            if path in items:
                items.remove(path)
            items.insert(0, path)
            items = items[:8]
            self.settings.setValue('recent_dests', '\n'.join(items))
        except Exception:
            pass

    def _load_recent_dests(self):
        if not self.settings:
            return
        try:
            cur = self.save_path_display.text().strip()
            if cur:
                return
            stored_raw = self.settings.value('recent_dests', '', type=str)
            stored = str(stored_raw) if stored_raw is not None else ''
            first = stored.split('\n')[0].strip() if isinstance(stored, str) and stored else ''
            if first and os.path.isdir(first):
                self.save_path_display.setText(first)
                self._update_clone_button_state()
        except Exception:
            pass

    # ----- helpers -----
    def _align_label_column(self):
        labels = [self.lbl_url, self.lbl_dest, self.lbl_img, self.lbl_bind_ip, self.lbl_port, self.lbl_cport]
        fm = QFontMetrics(labels[0].font())
        w = max(fm.horizontalAdvance(l.text()) for l in labels) + 8
        for l in labels:
            l.setFixedWidth(w)

    # ----- cookies import -----
    def scan_browser_cookies(self):
        from urllib.parse import urlparse
        import time
        url = None
        try:
            url = (self.url_input.currentText() or '').strip()
        except Exception:
            url = ''
        if not url:
            self.console.append("Enter a URL before scanning for cookies.")
            return
        # Be lenient: add scheme if missing and retry
        parsed = urlparse(url)
        if not parsed.hostname:
            if not url.lower().startswith(('http://','https://')):
                parsed = urlparse('https://' + url)
        host = (parsed.hostname or '').strip().lower()
        if not host and parsed.path:
            # One more fallback in case of odd inputs
            parsed2 = urlparse('https://' + parsed.path)
            host = (parsed2.hostname or '').strip().lower()
        if not host:
            self.console.append(f"Invalid URL; cannot determine hostname for cookie scan: {url}")
            return
        self.console.append(f"Scanning cookies for host: {host}")
        # Determine project directory for saving cookies file
        docker_name = self.docker_name_input.text().strip() or 'site'
        save_path = self.save_path_display.text().strip()
        if not save_path:
            self.console.append("Select a destination folder first (used to store imported cookies).")
            return
        proj_dir = os.path.abspath(os.path.join(save_path, docker_name))
        os.makedirs(proj_dir, exist_ok=True)

        cookies = []
        now = int(time.time())

        def add_cookie(domain, path, secure, expires, name, value, http_only=False):
            if not name:
                return
            dom = domain
            include_sub = 'TRUE' if dom.startswith('.') else 'FALSE'
            sec = 'TRUE' if secure else 'FALSE'
            exp = str(int(expires) if expires else now + 3600*24*30)
            line = f"{dom}\t{include_sub}\t{path or '/'}\t{sec}\t{exp}\t{name}\t{value}"
            # Netscape cookie file supports #HttpOnly_ prefix for domain
            if http_only:
                line = line  # optional: could prefix domain with #HttpOnly_
            cookies.append(line)

        # First, try browser_cookie3 (uses OS keychain to decrypt where supported)
        try:
            bc3 = importlib.import_module('browser_cookie3')
            jar = bc3.load(domain_name=host)
            for c in jar:
                # c.domain, c.path, c.secure, c.expires, c.name, c.value
                add_cookie(getattr(c, 'domain', ''), getattr(c, 'path', '/'), bool(getattr(c,'secure',False)),
                           int(getattr(c,'expires', now+3600*24*30) or 0), getattr(c,'name',''), getattr(c,'value',''),
                           bool(getattr(c,'_rest',{}).get('HttpOnly', False)))
            if cookies:
                self.console.append(f"Imported {len(cookies)} cookies via browser_cookie3.")
        except Exception:
            pass

        # Robust path: do not fall back; use only browser_cookie3
        total = len(cookies)
        if total > 0:
            cookies_path = os.path.join(proj_dir, 'imported_cookies.txt')
            try:
                with open(cookies_path, 'w', encoding='utf-8') as f:
                    f.write("# Netscape HTTP Cookie File\n")
                    for line in cookies:
                        f.write(line + "\n")
                self.imported_cookies_file = cookies_path
                self.use_cookies_checkbox.setEnabled(True)
                self.use_cookies_checkbox.setChecked(True)
                self.cookies_status.setText(f"Cookies imported: {total} → {os.path.basename(cookies_path)}")
            except Exception as e:
                self.console.append(f"Failed to write cookies file: {e}")
        else:
            self.imported_cookies_file = None
            self.use_cookies_checkbox.setChecked(False)
            self.use_cookies_checkbox.setEnabled(False)
            self.cookies_status.setText("No cookies imported")
        return

        # End cookie scan (browser_cookie3 only)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if folder: self.save_path_display.setText(folder)

    def fill_detected_ip(self):
        ip = get_primary_lan_ip()
        self.bind_ip_input.setText(ip)
        self.console.append(f"Detected LAN IP: {ip}")

    def _set_status_text_elided(self, full_text):
        metrics = QFontMetrics(self.status_label.font())
        width = max(50, self.status_label.width() - 24)
        elided = metrics.elidedText(full_text, Qt.TextElideMode.ElideRight, width)
        self.status_label.setText(elided)
        self.status_label.setToolTip(full_text)

    def resizeEvent(self, event):
        tip = self.status_label.toolTip()
        if tip: self._set_status_text_elided(tip)
        super().resizeEvent(event)

    def _enforce_splitter_minimums(self):
        return  # splitter removed; no-op
    def _finalize_sizing(self):
        # Compute an initial reasonable size that fits content width (to avoid horizontal scroll)
        screen = self.screen() or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        # Suggest a base size from content and card
        self.card.adjustSize()
        content_w = self.card.sizeHint().width() + 40
        # Also enforce left pane min width
        self._update_left_min_width()
        self.adjustSize()
        hint = self.sizeHint()
        w = max(content_w, hint.width())
        # Estimate non-client frame extra height (title bar/borders)
        try:
            frame_extra = (self.frameGeometry().height() - self.geometry().height()) if self.isVisible() else 40
            if frame_extra < 0:
                frame_extra = 40
        except Exception:
            frame_extra = 40
        # Prefer card's content height to avoid scroll, fall back to overall hint
        content_h = self.card.sizeHint().height() + frame_extra + 10
        h = max(hint.height(), content_h)
        if avail:
            # Fit everything if possible; otherwise cap to available screen
            w = min(w, avail.width())
            # Fit all content or fill screen vertically, whichever is smaller
            h = min(h, avail.height())
        # Minimum ensures layout doesn't squeeze too far; scroll area handles vertical overflow
        min_w = min(w, max(480, content_w))
        min_h = min(h, max(420, int((avail.height()*0.5) if avail else 520)))
        self.setMinimumSize(min_w, min_h)
        # Also enforce a hard minimum based on pane minimums to prevent overlap
        try:
            self._update_min_window_width()
        except Exception:
            pass
        if not getattr(self, "_geometry_restored", False):
            self.resize(w, h)

    def _load_window_settings(self) -> bool:
        try:
            geom = self.settings.value("geometry") if self.settings else None
            if geom is not None:
                self.restoreGeometry(geom)
                return True
        except Exception:
            pass
        return False

    def closeEvent(self, event):
        try:
            if self.settings:
                self.settings.setValue("geometry", self.saveGeometry())
        except Exception:
            pass
        super().closeEvent(event)

    # ----- recents -----
    def _load_recent_urls(self):
        items = []
        try:
            val = self.settings.value("recent_urls", []) if self.settings else []
            if isinstance(val, list):
                items = [str(v) for v in val if v]
            elif isinstance(val, str):
                items = [v for v in val.split('\n') if v]
        except Exception:
            items = []
        if items:
            self.url_input.clear()
            self.url_input.addItems(items[:10])

    def _remember_recent_url(self, url: str):
        if not url:
            return
        # Collect current list; ensure url at front, unique, capped to 10
        current = []
        try:
            for i in range(self.url_input.count()):
                current.append(self.url_input.itemText(i))
        except Exception:
            current = []
        urls = [url] + [u for u in current if u and u != url]
        urls = urls[:10]
        try:
            if self.settings:
                self.settings.setValue("recent_urls", urls)
        except Exception:
            pass
        # Update combo box items
        try:
            self.url_input.clear()
            self.url_input.addItems(urls)
            self.url_input.setCurrentText(url)
        except Exception:
            pass

    def update_status(self, running=False, mode="", port=None, cid=None):
        if running:
            elapsed = ""
            if self.container_start_time:
                delta = datetime.now() - self.container_start_time
                h_total = delta.days * 24 + delta.seconds // 3600
                m = (delta.seconds % 3600) // 60
                s = delta.seconds % 60
                elapsed = f" - Uptime: {h_total:02}:{m:02}:{s:02}"
            msg = f"Running [{mode}] on {self.current_host_ip}:{port} → container:{self.current_container_port} (ID: {cid}){elapsed}"
        elif cid is None:
            msg = "No container running"
        else:
            msg = f"Container {cid} stopped"

        if self.last_project_dir:
            msg += f" • Project: {self.last_project_dir}" if running else f" • Last project: {self.last_project_dir}"

        # Remember base status and set it
        self._status_base_text = msg
        self._set_status_text_elided(msg)

    def refresh_run_buttons(self):
        has_docker = docker_available()
        running = self.container_id is not None
        serve_ready = bool(self.last_project_dir and os.path.isdir(self.last_project_dir))

        self.run_folder_btn.setEnabled(has_docker and not running and serve_ready)
        if not serve_ready:
            self.run_folder_btn.setToolTip("Run after 'Clone  Prepare' prepares the folder.")
        elif not has_docker:
            self.run_folder_btn.setToolTip(f"Docker not found. Install:\n{docker_install_instructions()}")
        else:
            self.run_folder_btn.setToolTip("")

        img = self.docker_name_input.text().strip()
        if has_docker and not running and img and image_exists_locally(img):
            self.run_created_btn.setEnabled(True); self.run_created_btn.setToolTip("")
        else:
            self.run_created_btn.setEnabled(False)
            if not has_docker:
                self.run_created_btn.setToolTip(f"Docker not found. Install:\n{docker_install_instructions()}")
            elif running:
                self.run_created_btn.setToolTip("A container is running.")
            else:
                self.run_created_btn.setToolTip("Image not found locally. Build it first via 'Clone  Prepare' with 'Build Docker image after clone' checked.")
        self.clone_btn.setEnabled(not running)
        # Resume button is enabled when not running anything and a previous clone failed/canceled and folder exists
        cloning_active = bool(self.clone_thread and self.clone_thread.isRunning())
        self.cancel_clone_btn.setEnabled(cloning_active)
        self.resume_btn.setEnabled((not running) and (not cloning_active) and serve_ready and self.last_clone_failed_or_canceled)

    # ----- actions -----
    def start_clone(self):
        # Snapshot inputs via helper for clarity
        snapshot = self._snapshot_inputs()
        if not snapshot:
            return
        # Show overall progress bar (fade in)
        try:
            if hasattr(self, 'total_progress_bar') and self.total_progress_bar:
                self.total_progress_bar.setValue(0)
                if hasattr(self, '_fade_progress'):
                    self._fade_progress(True)
                else:
                    self.total_progress_bar.setVisible(True)
        except Exception:
            pass
        self.console.clear()
        if snapshot.estimate_first:
            self.console.append("Estimation prepass: enabled")
        else:
            self.console.append("Estimation prepass: disabled")
        if snapshot.parallel_jobs > 1:
            self.console.append(f"Parallel downloads: enabled • jobs={snapshot.parallel_jobs}")
        else:
            self.console.append("Parallel downloads: disabled")
        if snapshot.http_user and not snapshot.http_password:
            self.console.append("HTTP auth username provided; password empty.")
        # Worker
        worker = CloneThread(
            snapshot.url, snapshot.project_dir_name, snapshot.save_path,
            snapshot.build_docker,
            host_port=snapshot.host_port, size_cap=snapshot.size_cap, throttle=snapshot.throttle,
            host_ip=snapshot.host_ip, container_port=snapshot.container_port,
            http_user=snapshot.http_user, http_password=snapshot.http_password,
            pre_existing_count=snapshot.pre_existing, pre_partial_count=snapshot.pre_partial,
            estimate_first=snapshot.estimate_first, parallel_jobs=snapshot.parallel_jobs,
            disable_js=snapshot.disable_js,
            prerender=snapshot.prerender, prerender_max_pages=snapshot.prerender_max_pages,
            capture_api=snapshot.capture_api, hook_script=snapshot.hook_script,
            rewrite_urls=snapshot.rewrite_urls,
            router_intercept=snapshot.router_intercept, router_include_hash=snapshot.router_include_hash,
            router_max_routes=snapshot.router_max_routes, router_settle_ms=snapshot.router_settle_ms,
            router_wait_selector=snapshot.router_wait_selector,
            router_allow=snapshot.router_allow, router_deny=snapshot.router_deny,
            cookies_file=snapshot.cookies_file,
            no_manifest=snapshot.no_manifest,
            checksums=snapshot.checksums,
            checksum_extra_ext=snapshot.checksum_extra_ext
        )
        if snapshot.router_quiet:
            worker.router_quiet = True
        self.clone_thread = worker
        worker.progress.connect(self.update_console)
        worker.total_progress.connect(self.update_total_progress)
        worker.bandwidth.connect(self.update_bandwidth)
        worker.api_capture.connect(self.update_api_capture)
        worker.router_count.connect(self.update_router_count)
        worker.finished.connect(self.clone_finished)
        if snapshot.verify_after:
            orig = self.clone_finished
            def _wrap(log_text: str, docker_ok: bool, clone_ok: bool):
                orig(log_text, docker_ok, clone_ok)
                def do_verify():
                    manifest_path = os.path.join(self.last_project_dir or '', 'clone_manifest.json')
                    if not (manifest_path and os.path.exists(manifest_path)):
                        self.console.append('[verify] Manifest not found; skipping')
                        return
                    self.console.append('[verify] Running checksum verification…')
                    fast = snapshot.verify_fast
                    passed, stats = run_verification(
                        manifest_path,
                        fast=fast,
                        docker_name=snapshot.project_dir_name,
                        project_dir=self.last_project_dir,
                        output_cb=lambda line: self.console.append(line)
                    )
                    self._update_verification_badge(passed, stats)
                    self.console.append('[verify] PASSED' if passed else '[verify] FAILED (see above)')
                QTimer.singleShot(0, do_verify)
            try:
                worker.finished.disconnect(self.clone_finished)
            except Exception:
                pass
            worker.finished.connect(_wrap)
        self.clone_btn.setEnabled(False)
        self.cancel_clone_btn.setEnabled(True)
        self.last_clone_failed_or_canceled = False
        if snapshot.url:
            self._remember_recent_url(snapshot.url)
        worker.start()

    # --- configuration snapshot support ---
    @dataclass
    class _ConfigSnapshot:
        url: str
        project_dir_name: str
        save_path: str
        build_docker: bool
        host_port: int
        container_port: int
        host_ip: str
        size_cap: int | None
        throttle: int | None
        http_user: str | None
        http_password: str | None
        estimate_first: bool
        parallel_jobs: int
        disable_js: bool
        prerender: bool
        prerender_max_pages: int
        capture_api: bool
        hook_script: str | None
        rewrite_urls: bool
        router_intercept: bool
        router_include_hash: bool
        router_max_routes: int
        router_settle_ms: int
        router_wait_selector: str | None
        router_allow: list[str] | None
        router_deny: list[str] | None
        cookies_file: str | None
        no_manifest: bool
        checksums: bool
        checksum_extra_ext: list[str] | None
        pre_existing: int
        pre_partial: int
        verify_after: bool
        verify_fast: bool
        router_quiet: bool

    def _snapshot_inputs(self) -> Optional['_ConfigSnapshot']:
        """Validate and capture current form inputs into a _ConfigSnapshot.

        Performs:
          - Dependency check for wget2
          - Guard against starting while a container is already running
          - Required field validation (URL, destination, bind IP, image name when building)
          - Inline visual highlight of invalid widgets (temporary red border)
          - Resume detection counting existing + partial files
          - Optional port conflict prompt with opportunity to choose a new port
          - Construction of target project directory name/path

        Returns:
          _ConfigSnapshot instance if all validation passes, else None.
        """
        if not is_wget2_available():
            self.console.append("Required dependency missing: wget2. Click 'Fix Dependencies…' to copy an install command.")
            return None
        if self.container_id is not None:
            self.console.append("Stop the running container before creating a new one.")
            return None
        try:
            url = self.url_input.currentText().strip()
        except Exception:
            url = str(getattr(self.url_input, 'text', lambda: '')()).strip()
        docker_name = self.docker_name_input.text().strip()
        save_path = self.save_path_display.text().strip()
        host_port = self.port_input.value()
        container_port = self.cport_input.value()
        ip_text = normalize_ip(self.bind_ip_input.text())
        # Inline validation with transient highlight
        invalid = []
        def flash(widget):
            try:
                orig = widget.styleSheet()
                widget.setStyleSheet(orig + ';border:2px solid #c0392b;')
                QTimer.singleShot(1400, lambda: widget.setStyleSheet(orig))
            except Exception:
                pass
        if not url:
            invalid.append((self.url_input, 'Website URL is required.'))
        if not save_path:
            invalid.append((self.save_path_display, 'Destination Folder is required.'))
        if not ip_text:
            invalid.append((self.bind_ip_input, 'Invalid Bind IP.'))
        if self.build_checkbox.isChecked() and not docker_name:
            invalid.append((self.docker_name_input, 'Docker image name required when building an image.'))
        if invalid:
            for w, msg in invalid:
                flash(w)
            self.console.append("Validation errors:\n - " + "\n - ".join(m for _, m in invalid))
            try:
                self.clone_btn.setEnabled(False)
            except Exception:
                pass
            return None
        else:
            try:
                if self.container_id is None and (not self.clone_thread or not self.clone_thread.isRunning()):
                    self.clone_btn.setEnabled(True)
            except Exception:
                pass
        self.current_host_ip = ip_text
        self.current_port = host_port
        self.current_container_port = container_port
        project_dir_name = docker_name if docker_name else 'site'
        self.last_project_dir = os.path.abspath(os.path.join(save_path, project_dir_name))
        try:
            if hasattr(self, 'open_folder_btn') and self.open_folder_btn:
                self.open_folder_btn.setEnabled(True)
        except Exception:
            pass
        self.update_status(False, cid=None)
        try:
            resume = os.path.isdir(self.last_project_dir) and any(True for _ in os.scandir(self.last_project_dir))
        except Exception:
            resume = False
        pre_existing = pre_partial = 0
        if resume:
            pre_existing, pre_partial = count_files_and_partials(self.last_project_dir)
            self.resuming_label.setText(f'Cloning (resuming) • Existing: {pre_existing} • Partial: {pre_partial}')
            self.resuming_label.setVisible(True)
            self.console.append(f'Existing files detected: {pre_existing} • partial: {pre_partial}')
        else:
            self.resuming_label.setVisible(False)
        if port_in_use(ip_text, host_port):
            self.console.append(f'Port {host_port} appears in use on {ip_text}.')
            default = max(1, min(65535, host_port + 1))
            port, ok = QInputDialog.getInt(self, 'Port in Use', 'Enter a different port:', default, 1, 65535)
            if not ok:
                return None
            host_port = port
            self.port_input.setValue(port)
            self.current_port = port
        size_cap = None
        if self.size_cap_checkbox.isChecked():
            mul = {"MB":1024**2, "GB":1024**3, "TB":1024**4}[self.size_cap_unit.currentText()]
            size_cap = self.size_cap_value.value() * mul
        throttle = None
        if self.throttle_checkbox.isChecked():
            mul = 1024 if self.throttle_unit.currentText() == 'KB/s' else 1024**2
            throttle = self.throttle_value.value() * mul
        http_user = http_password = None
        if self.auth_checkbox.isChecked():
            http_user = self.auth_user_input.text().strip()
            http_password = self.auth_pass_input.text()
        estimate_first = self.estimate_checkbox.isChecked()
        parallel_jobs = self.parallel_jobs_input.value() if self.parallel_checkbox.isChecked() else 1
        disable_js = self.disable_js_checkbox.isChecked()
        prerender = hasattr(self,'prerender_checkbox') and self.prerender_checkbox and self.prerender_checkbox.isChecked()
        prerender_max_pages = self.prerender_pages_spin.value() if (hasattr(self,'prerender_pages_spin') and self.prerender_pages_spin) else DEFAULT_PRERENDER_MAX_PAGES
        capture_api = hasattr(self,'capture_api_checkbox') and self.capture_api_checkbox and self.capture_api_checkbox.isChecked()
        hook_script = getattr(self,'hook_script_path', None)
        rewrite_urls = not (hasattr(self,'no_rewrite_checkbox') and self.no_rewrite_checkbox and self.no_rewrite_checkbox.isChecked())
        router_intercept = hasattr(self,'router_intercept_checkbox') and self.router_intercept_checkbox.isChecked()
        router_include_hash = hasattr(self,'router_hash_checkbox') and self.router_hash_checkbox.isChecked()
        router_max_routes = self.router_max_routes_spin.value() if hasattr(self,'router_max_routes_spin') else DEFAULT_ROUTER_MAX_ROUTES
        router_settle_ms = self.router_settle_spin.value() if hasattr(self,'router_settle_spin') else DEFAULT_ROUTER_SETTLE_MS
        router_wait_selector = (self.router_wait_selector_edit.text().strip() or None) if hasattr(self,'router_wait_selector_edit') else None
        router_allow = ([p.strip() for p in self.router_allow_edit.text().split(',') if p.strip()] if (hasattr(self,'router_allow_edit') and self.router_allow_edit.isEnabled() and self.router_allow_edit.text().strip()) else None)
        router_deny = ([p.strip() for p in self.router_deny_edit.text().split(',') if p.strip()] if (hasattr(self,'router_deny_edit') and self.router_deny_edit.isEnabled() and self.router_deny_edit.text().strip()) else None)
        cookies_file = getattr(self, 'imported_cookies_file', None) if (hasattr(self,'use_cookies_checkbox') and self.use_cookies_checkbox.isChecked()) else None
        no_manifest = hasattr(self,'skip_manifest_checkbox') and self.skip_manifest_checkbox.isChecked()
        checksums = hasattr(self,'checksums_checkbox') and self.checksums_checkbox.isChecked()
        checksum_extra_ext = []
        if hasattr(self,'checksum_extra_edit') and self.checksum_extra_edit.text().strip():
            checksum_extra_ext = [e.strip() for e in self.checksum_extra_edit.text().split(',') if e.strip()]
        verify_after = hasattr(self,'verify_checksums_checkbox') and self.verify_checksums_checkbox.isChecked()
        verify_fast = True
        if hasattr(self,'verify_fast_checkbox') and self.verify_fast_checkbox.isEnabled():
            verify_fast = self.verify_fast_checkbox.isChecked()
        router_quiet = hasattr(self,'router_quiet_checkbox') and self.router_quiet_checkbox.isEnabled() and self.router_quiet_checkbox.isChecked()
        return self._ConfigSnapshot(
            url=url, project_dir_name=project_dir_name, save_path=save_path,
            build_docker=self.build_checkbox.isChecked(), host_port=host_port, container_port=container_port,
            host_ip=ip_text, size_cap=size_cap, throttle=throttle, http_user=http_user, http_password=http_password,
            estimate_first=estimate_first, parallel_jobs=parallel_jobs, disable_js=disable_js,
            prerender=prerender, prerender_max_pages=prerender_max_pages, capture_api=capture_api, hook_script=hook_script,
            rewrite_urls=rewrite_urls, router_intercept=router_intercept, router_include_hash=router_include_hash,
            router_max_routes=router_max_routes, router_settle_ms=router_settle_ms, router_wait_selector=router_wait_selector,
            router_allow=router_allow, router_deny=router_deny, cookies_file=cookies_file, no_manifest=no_manifest,
            checksums=checksums, checksum_extra_ext=(checksum_extra_ext or None), pre_existing=pre_existing,
            pre_partial=pre_partial, verify_after=verify_after, verify_fast=verify_fast, router_quiet=router_quiet
        )

    # --- verification badge helper ---
    def _update_verification_badge(self, passed: bool, stats: dict):
        try:
            if not hasattr(self,'verify_status_label'):
                return
            if passed:
                if stats.get('ok') is not None and stats.get('total') is not None:
                    self.verify_status_label.setText(f"VERIFY OK {stats['ok']}/{stats['total']}")
                else:
                    self.verify_status_label.setText("VERIFY OK")
                self.verify_status_label.setStyleSheet(VERIFY_BADGE_STYLE_OK)
            else:
                self.verify_status_label.setText("VERIFY FAIL")
                self.verify_status_label.setStyleSheet(VERIFY_BADGE_STYLE_FAIL)
            self.verify_status_label.setVisible(True)
        except Exception:
            pass

    def cancel_clone(self):
        if not (self.clone_thread and self.clone_thread.isRunning()):
            self.cancel_clone_btn.setEnabled(False)
            return
        choice = QMessageBox.question(
            self,
            "Cancel Clone?",
            "Are you sure you want to cancel the current clone?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        try:
            self.clone_thread.request_stop()
            self.console.append("Cancel requested. Stopping clone…")
        except Exception as e:
            self.console.append(f"Failed to request cancel: {e}")
        self.cancel_clone_btn.setEnabled(False)

    def _ensure_folder_nginx_conf(self, container_port: int) -> str:
        """
        Create a minimal nginx conf in the project folder so nginx:alpine
        can listen on the chosen container_port for folder mode.
        """
        if not self.last_project_dir:
            return ""
        conf_path = os.path.join(self.last_project_dir, f".folder.default.{container_port}.conf")
        try:
            with open(conf_path, "w", encoding="utf-8") as f:
                hdr = "    add_header Content-Security-Policy \"script-src 'none'; frame-src 'none'\" always;\n" if (hasattr(self,'disable_js_checkbox') and self.disable_js_checkbox.isChecked()) else ""
                f.write(
                    "server {\n"
                    f"    listen {container_port};\n"
                    "    server_name localhost;\n"
                    "    root /usr/share/nginx/html;\n"
                    "    index index.html;\n"
                    + hdr +
                    "    location / { try_files $uri $uri/ =404; }\n"
                    "}\n"
                )
        except Exception as e:
            self.console.append(f"Failed to create nginx folder config: {e}")
            return ""
        return conf_path

    def run_created_container(self):
        if not docker_available():
            self.console.append("Docker not installed."); self.refresh_run_buttons(); return
        if self.container_id is not None:
            self.console.append("A container is already running. Stop it first."); return

        image = self.docker_name_input.text().strip()
        if not image:
            self.console.append("Docker image name is required."); self.refresh_run_buttons(); return
        if not image_exists_locally(image):
            self.console.append(f"Image '{image}' not found locally.\nTip: Run 'Clone  Prepare' with 'Build Docker image after clone' checked to create it.")
            self.refresh_run_buttons(); return

        bind_ip = normalize_ip(self.bind_ip_input.text())
        if not bind_ip:
            self.console.append("Invalid Bind IP."); return
        if port_in_use(bind_ip, self.port_input.value()):
            self.console.append(f"Port {self.port_input.value()} appears in use on {bind_ip}.")
            default = max(1, min(65535, self.port_input.value() + 1))
            port, ok = QInputDialog.getInt(self, "Port in Use", "Enter a different port:", default, 1, 65535)
            if not ok: return
            self.port_input.setValue(port)

        host_p = self.port_input.value()
        cont_p = self.cport_input.value()

        res = subprocess.run(
            ["docker","run","-d","-p",f"{bind_ip}:{host_p}:{cont_p}", image],
            capture_output=True, text=True
        )
        if res.returncode == 0:
            self.container_id = res.stdout.strip()
            display_host = "localhost" if bind_ip == "0.0.0.0" else bind_ip
            self.container_url = f"http://{display_host}:{host_p}"
            self.container_start_time = datetime.now()
            self.current_host_ip = bind_ip
            self.current_port = host_p
            self.current_container_port = cont_p
            self.copy_url_btn.setEnabled(True); self.open_url_btn.setEnabled(True)
            self.update_status(True,"Created Image",host_p,self.container_id)
            self.console.append(f"Running created container at {self.container_url} (ID: {self.container_id})")
            self.stop_btn.setEnabled(True); self.clone_btn.setEnabled(False)
            self.refresh_run_buttons()
        else:
            self.console.append(f"Failed to start container: {res.stderr.strip()}")

    def run_from_folder(self):
        if not docker_available():
            self.console.append("Docker not installed."); self.refresh_run_buttons(); return
        if self.container_id is not None:
            self.console.append("A container is already running. Stop it first."); return

        folder = self.last_project_dir
        site_root = find_site_root(folder)
        if not folder or not os.path.isdir(folder):
            self.console.append("No prepared project folder. Run 'Clone  Prepare' first."); return

        bind_ip = normalize_ip(self.bind_ip_input.text())
        if not bind_ip:
            self.console.append("Invalid Bind IP."); return
        if port_in_use(bind_ip, self.port_input.value()):
            self.console.append(f"Port {self.port_input.value()} appears in use on {bind_ip}.")
            default = max(1, min(65535, self.port_input.value() + 1))
            port, ok = QInputDialog.getInt(self, "Port in Use", "Enter a different port:", default, 1, 65535)
            if not ok: return
            self.port_input.setValue(port)

        host_p = self.port_input.value()
        cont_p = self.cport_input.value()

        conf_path = self._ensure_folder_nginx_conf(cont_p)
        if not conf_path:
            return

        res = subprocess.run(
            ["docker","run","-d","-p",f"{bind_ip}:{host_p}:{cont_p}",
             "-v",f"{site_root}:/usr/share/nginx/html",
             "-v",f"{conf_path}:/etc/nginx/conf.d/default.conf:ro",
             "nginx:alpine"],
            capture_output=True, text=True
        )
        if res.returncode == 0:
            self.container_id = res.stdout.strip()
            display_host = "localhost" if bind_ip == "0.0.0.0" else bind_ip
            self.container_url = f"http://{display_host}:{host_p}"
            self.container_start_time = datetime.now()
            self.current_host_ip = bind_ip
            self.current_port = host_p
            self.current_container_port = cont_p
            self.copy_url_btn.setEnabled(True); self.open_url_btn.setEnabled(True)
            self.update_status(True,"Folder Mode",host_p,self.container_id)
            self.console.append(f"Serving from folder at {self.container_url} (ID: {self.container_id})")
            self.stop_btn.setEnabled(True); self.clone_btn.setEnabled(False)
            self.refresh_run_buttons()
        else:
            self.console.append(f"Failed to serve from folder: {res.stderr.strip()}")

    def stop_container(self):
        if self.container_id:
            subprocess.run(["docker","stop",self.container_id])
            self.update_status(False,cid=self.container_id)
        self.container_id = None; self.container_url = None; self.container_start_time = None
        self.stop_btn.setEnabled(False); self.copy_url_btn.setEnabled(False); self.open_url_btn.setEnabled(False)
        self.clone_btn.setEnabled(True); self.refresh_run_buttons()

    def copy_url(self):
        if not self.container_url: return
        QGuiApplication.clipboard().setText(self.container_url)
        self.console.append(f"URL copied: {self.container_url}")

    def open_in_browser(self):
        if not self.container_url:
            self.console.append("No running container URL to open."); return
        webbrowser.open(self.container_url)

    def check_container_status(self):
        if self.container_id:
            res = subprocess.run(["docker","ps","-q","-f",f"id={self.container_id}"],capture_output=True,text=True)
            if res.returncode==0 and not res.stdout.strip():
                self.update_status(False,cid=self.container_id)
                self.container_id=None; self.container_url=None; self.container_start_time=None
                self.stop_btn.setEnabled(False); self.copy_url_btn.setEnabled(False); self.open_url_btn.setEnabled(False)
                self.clone_btn.setEnabled(True)
        self.refresh_run_buttons()
        self.refresh_deps_panel()

    def update_console(self, msg):
        self.console.append(msg); self.console.ensureCursorVisible()

    def refresh_deps_panel(self):
        has_wget2 = is_wget2_available()
        has_docker = docker_available()
        try:
            importlib.import_module('browser_cookie3'); has_bc3 = True
        except Exception:
            has_bc3 = False

        # Show the dependency frame if anything is missing
        any_missing = not (has_wget2 and has_docker and has_bc3)
        self.deps_frame.setVisible(any_missing)
        self.dep_wget2_label.setText("wget2: Installed" if has_wget2 else "wget2: Missing")
        self.dep_docker_label.setText("Docker: Installed" if has_docker else "Docker: Missing")
        self.dep_bc3_label.setText("browser_cookie3: Installed" if has_bc3 else "browser_cookie3: Missing")
        # Toggle visibility of the main-window dialog button
        self.deps_dialog_btn.setVisible(any_missing)

        # Apply feature gating: wget2 gates cloning; Docker gates build/run; bc3 only gates cookie scan
        self._apply_dependency_gating(has_wget2, has_docker, has_bc3)

    def run_dependency_dialog_if_needed(self):
        """Initial dependency check; updates banner and gating (no auto-install popups)."""
        self.refresh_deps_panel()

    def _apply_dependency_gating(self, has_wget2: bool, has_docker: bool, has_bc3: bool):
        # Clone/source controls gated by wget2
        for w in [self.url_input, self.save_path_display,
                  self.size_cap_checkbox, self.size_cap_value, self.size_cap_unit,
                  self.throttle_checkbox, self.throttle_value, self.throttle_unit,
                  self.auth_checkbox, self.auth_user_input, self.auth_pass_input,
                  self.estimate_checkbox, self.parallel_checkbox, self.parallel_jobs_input,
                  self.disable_js_checkbox]:
            try:
                w.setEnabled(has_wget2)
            except Exception:
                pass

        # Cookie scan only when bc3 present; cookie toggle follows clone gating
        try:
            self.scan_cookies_btn.setEnabled(has_wget2 and has_bc3)
        except Exception:
            pass
        try:
            self.use_cookies_checkbox.setEnabled(has_wget2 and bool(getattr(self, 'imported_cookies_file', None)))
        except Exception:
            pass

        # Docker-related: build + run buttons gated by Docker
        for w in [self.build_checkbox, self.docker_name_input,
                  self.run_created_btn, self.run_folder_btn, self.stop_btn]:
            try:
                w.setEnabled(has_docker)
            except Exception:
                pass

        # Keep run IP/ports editable even if Docker is missing
        for w in [self.bind_ip_input, self.port_input, self.cport_input]:
            try:
                w.setEnabled(True)
            except Exception:
                pass

        # Clone/resume buttons: clone needs wget2; resume just starts clone flow, so same
        try:
            if not has_wget2:
                self.clone_btn.setEnabled(False)
                self.resume_btn.setEnabled(False)
        except Exception:
            pass

        # Keep the deps dialog button enabled regardless
        try:
            self.deps_dialog_btn.setEnabled(True)
        except Exception:
            pass

        # Let normal run button logic refine state (running container, image present, etc.)
        try:
            self.refresh_run_buttons()
        except Exception:
            pass

    def show_dependencies_dialog(self):
        """Show a dialog listing missing dependencies with per-item copy install commands."""
        dlg = QDialog(self); dlg.setWindowTitle('Missing Dependencies')
        try:
            from PySide6.QtCore import Qt as _Qt
            dlg.setWindowModality(_Qt.WindowModality.ApplicationModal)
        except Exception:
            pass
        v = QVBoxLayout(dlg)
        header = QLabel('Missing dependencies. Click Copy to copy an install command for your OS.')
        v.addWidget(header)

        # Dynamic list area
        list_container = QVBoxLayout()
        list_container.setContentsMargins(0,0,0,0)
        v.addLayout(list_container)

        def build_missing_list():
            items = []
            if not is_wget2_available():
                cmd = get_install_cmd('wget2')
                items.append(('wget2', (' '.join(cmd) if cmd else None), 'https://gitlab.com/gnuwget/wget2#installation'))
            if not docker_available():
                cmd = get_install_cmd('docker')
                items.append(('Docker', (' '.join(cmd) if cmd else None), 'https://docs.docker.com/get-docker/'))
            try:
                importlib.import_module('browser_cookie3'); have_bc3 = True
            except Exception:
                have_bc3 = False
            if not have_bc3:
                items.append(('browser_cookie3 (optional)', f"{sys.executable} -m pip install browser_cookie3", None))
            return items

        def clear_layout(lo: QLayout):
            try:
                while lo.count():
                    item = lo.takeAt(0)
                    w = item.widget()
                    if w is not None:
                        w.setParent(None)
                    sub = item.layout()
                    if sub is not None:
                        clear_layout(sub)
            except Exception:
                pass

        def populate():
            clear_layout(list_container)
            items = build_missing_list()
            if not items:
                list_container.addWidget(QLabel('All dependencies are installed.'))
                return
            for name, cmd, docs in items:
                row = QHBoxLayout(); row.setContentsMargins(0,0,0,0)
                lbl = QLabel(f"{name}: Missing")
                row.addWidget(lbl)
                copy_btn = QPushButton('Copy install command')
                def make_copy(c=cmd, n=name):
                    def _():
                        if c:
                            QGuiApplication.clipboard().setText(c)
                            self.console.append(f"Copied {n} install cmd: {c}")
                        else:
                            self.console.append(f"No automatic command for {n}. See docs.")
                    return _
                copy_btn.clicked.connect(make_copy())
                row.addWidget(copy_btn)
                if docs:
                    docs_btn = QPushButton('Open docs')
                    def make_docs(url=docs):
                        def _():
                            try:
                                webbrowser.open(url)
                            except Exception:
                                pass
                        return _
                    docs_btn.clicked.connect(make_docs())
                    row.addWidget(docs_btn)
                row.addStretch(1)
                list_container.addLayout(row)

        populate()

        btns = QHBoxLayout(); btns.addStretch(1)
        recheck_btn = QPushButton('Recheck')
        close_btn = QPushButton('Close')
        btns.addWidget(recheck_btn)
        btns.addWidget(close_btn)
        v.addLayout(btns)

        def do_recheck():
            # Refresh banner/gating and repopulate list in-place
            self.refresh_deps_panel()
            populate()
        recheck_btn.clicked.connect(do_recheck)
        close_btn.clicked.connect(dlg.accept)
        dlg.exec()

    def copy_wget2_install_cmd(self):
        cmd = get_install_cmd("wget2")
        if not cmd:
            self.console.append("No automatic install command for wget2 on this OS. Opening docs…")
            self.open_wget2_docs()
            return
        text = " ".join(cmd)
        QGuiApplication.clipboard().setText(text)
        self.console.append(f"Copied wget2 install cmd: {text}")

    def copy_docker_install_cmd(self):
        cmd = get_install_cmd("docker")
        if not cmd:
            self.console.append("No automatic install command for Docker on this OS. Opening docs…")
            self.open_docker_docs()
            return
        text = " ".join(cmd)
        QGuiApplication.clipboard().setText(text)
        self.console.append(f"Copied Docker install cmd: {text}")

    def copy_browser_cookie_install_cmd(self):
        text = f"{sys.executable} -m pip install browser_cookie3"
        QGuiApplication.clipboard().setText(text)
        self.console.append("Copied browser_cookie3 install cmd: " + text)

    def open_wget2_docs(self):
        try:
            webbrowser.open("https://gitlab.com/gnuwget/wget2#installation")
        except Exception:
            pass

    def open_docker_docs(self):
        try:
            webbrowser.open("https://docs.docker.com/get-docker/")
        except Exception:
            pass

    def set_controls_enabled(self, enabled: bool):
        # Disable the main card to block usage when requirements are missing
        self.card.setEnabled(enabled)

    # Dependency gating centralized in run_dependency_dialog_if_needed.

    def clone_finished(self, log, docker_success, clone_success):
        """Finalize UI and status after the clone/build worker finishes.

        Args:
            log: (unused legacy param from older signal signature; retained for compatibility)
            docker_success: whether any requested Docker build step succeeded
            clone_success: whether the wget2 clone phase reported success

        Side-effects:
            - Restores buttons / resume state
            - Emits user notifications
            - Fades out progress bar (animated if supported)
            - Updates status line & verification badge visibility
        """
        self.console.append("\nProcess finished.")
        self.refresh_run_buttons()
        self.update_status(False, cid=None)
        self.console.ensureCursorVisible()
        # restore status text after tasks complete
        self._set_status_text_elided(self._status_base_text)
        self.resuming_label.setVisible(False)
        # Re-enable clone button (unless a container started running elsewhere)
        if self.container_id is None:
            self.clone_btn.setEnabled(True)
        self.cancel_clone_btn.setEnabled(False)
        self.last_clone_failed_or_canceled = not bool(clone_success)
        self.resume_btn.setEnabled(self.last_clone_failed_or_canceled and bool(self.last_project_dir))
        # Popup notifications for clone result
        if clone_success:
            QMessageBox.information(self, "Clone Completed", "Website clone completed successfully. You can build or run now.")
        else:
            QMessageBox.warning(self, "Clone Failed", "Website cloning failed. You can fix the issue and run Clone again to resume.")
        # Fade out overall progress bar
        try:
            if hasattr(self, '_fade_progress'):
                self._fade_progress(False)
            elif hasattr(self, 'total_progress_bar') and self.total_progress_bar:
                self.total_progress_bar.setVisible(False)
        except Exception:
            pass

    def update_total_progress(self, percent: int, phase: str):
        """Update consolidated progress bar while enforcing intra-phase monotonicity."""
        # Guard & clamp percent; ignore regressions unless phase changes
        try:
            pct = int(percent)
        except Exception:
            pct = 0
        if pct < 0:
            pct = 0
        if pct > 100:
            pct = 100
        prev_phase = getattr(self, '_current_phase_title', None)
        prev_pct = getattr(self, '_current_percent', -1)
        phase_title = {
            'clone': 'Cloning',
            'prerender': 'Prerender (dynamic pages)',
            'build': 'Docker build',
            'cleanup': 'Cleanup'
        }.get(phase, phase.title())
        # Only accept lower progress if phase advanced
        if pct < prev_pct and phase_title == prev_phase:
            return
        self._current_percent = pct
        self._current_phase_title = phase_title
        try:
            if hasattr(self, 'total_progress_bar') and self.total_progress_bar:
                self.total_progress_bar.setValue(pct)
        except Exception:
            pass
        self._rebuild_status_line()

    def update_bandwidth(self, rate: str):
        """Record current formatted bandwidth rate and refresh the aggregated status line."""
        self._current_rate = rate
        self._rebuild_status_line()

    def update_api_capture(self, count: int):
        """Update API request capture count with throttled UI repaint conditions."""
        # Throttle UI refresh to avoid excessive updates on high-frequency API responses
        import time
        now = time.time()
        last_time = getattr(self, '_last_api_ui_emit_time', 0.0)
        last_count = getattr(self, '_last_api_ui_count', -1)
        self._current_api_count = count
        # Conditions to update: first time, count divisible by 5, time elapsed >0.4s, or large jump (>20)
        if (last_count == -1 or
            count % 5 == 0 or
            (now - last_time) > 0.4 or
            (count - last_count) > 20):
            self._last_api_ui_emit_time = now
            self._last_api_ui_count = count
            self._rebuild_status_line()

    def update_router_count(self, count: int):
        """Update discovered route count for SPA interception (throttled like API count)."""
        import time
        now = time.time()
        last_time = getattr(self, '_last_router_ui_emit_time', 0.0)
        last_count = getattr(self, '_last_router_ui_count', -1)
        self._current_router_count = count
        if (last_count == -1 or
            count % 3 == 0 or
            (now - last_time) > 0.5 or
            (count - last_count) > 10):
            self._last_router_ui_emit_time = now
            self._last_router_ui_count = count
            self._rebuild_status_line()

    def _rebuild_status_line(self):
        base = getattr(self, '_status_base_text', '') or ''
        parts = []
        if hasattr(self, '_current_percent') and hasattr(self, '_current_phase_title'):
            parts.append(f"Total progress: {self._current_percent}% • {self._current_phase_title}")
        if hasattr(self, '_current_rate'):
            parts.append(f"Rate: {self._current_rate}")
        if hasattr(self, '_current_api_count'):
            parts.append(f"API: {self._current_api_count}")
        if hasattr(self, '_current_router_count'):
            parts.append(f"Routes: {self._current_router_count}")
        suffix = " • ".join(parts) if parts else ''
        if base and suffix:
            text = f"{base} • {suffix}"
        elif base:
            text = base
        else:
            text = suffix
        self._set_status_text_elided(text)

    # --- progress bar fade helper (inserted late to avoid forward ref issues) ---
    def _fade_progress(self, show: bool):  # safe fallback if opacity effects unavailable
        """Animate (or toggle) visibility of the overall progress bar.

        Attempts an opacity animation; if effects/animation unsupported,
        degrades to immediate show/hide so progress remains visible.
        """
        try:
            if not hasattr(self, 'total_progress_bar') or not self.total_progress_bar:
                return
            bar = self.total_progress_bar
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            from PySide6.QtCore import QPropertyAnimation, QEasingCurve
            eff = getattr(bar, '_fade_effect', None)
            if eff is None:
                eff = QGraphicsOpacityEffect(bar)
                bar.setGraphicsEffect(eff)
                setattr(bar, '_fade_effect', eff)
            anim = getattr(bar, '_fade_anim', None)
            if anim is not None:
                try: anim.stop()
                except Exception: pass
            anim = QPropertyAnimation(eff, b"opacity", bar)
            anim.setDuration(260)
            anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
            start = eff.opacity() if not show else 0.0
            end = 1.0 if show else 0.0
            if show and not bar.isVisible():
                bar.setVisible(True)
            if show and eff.opacity() > 0.95:
                return
            anim.setStartValue(start)
            anim.setEndValue(end)
            def _finish():
                if not show:
                    bar.setVisible(False)
            anim.finished.connect(_finish)
            setattr(bar, '_fade_anim', anim)
            anim.start()
        except Exception:
            try:
                self.total_progress_bar.setVisible(show)
            except Exception:
                pass

# ---------- main ----------
if __name__ == "__main__":
    if '--headless' in sys.argv:
        # Run CLI mode without creating a QApplication
        # Remove the flag to avoid confusion in argparse help
        argv = [a for a in sys.argv[1:] if a != '--headless']
        code = headless_main(argv)
        sys.exit(code)
    # GUI mode — rely entirely on Qt's defaults; no HiDPI overrides
    app = QApplication(sys.argv)
    icon_path = find_icon("icon.png")
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))
    window = DockerClonerGUI()
    window.show()
    sys.exit(app.exec())
