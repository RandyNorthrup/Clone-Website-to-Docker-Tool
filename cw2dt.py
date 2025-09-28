import sys, os, subprocess, shutil, platform, socket, webbrowser, ipaddress, importlib
from datetime import datetime

# Qt imports are deferred until after headless handling to allow running without PySide6 installed.

# ---------- helpers ----------
PARTIAL_SUFFIXES = {".tmp", ".part", ".partial", ".download"}

def count_files_and_partials(base_path: str):
    total = 0
    partials = 0
    if not base_path or not os.path.isdir(base_path):
        return 0, 0
    for root, dirs, files in os.walk(base_path):
        for f in files:
            total += 1
            name = f.lower()
            for suf in PARTIAL_SUFFIXES:
                if name.endswith(suf):
                    partials += 1
                    break
    return total, partials
def is_wget2_available():
    try:
        subprocess.run(["wget2", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False

def get_install_cmd(program: str):
    """
    Return a best-effort install command list for the given program based on OS and available package manager.
    program: one of 'wget2' or 'docker'.
    """
    mgrs_linux = [
        "apt-get", "apt", "dnf", "yum", "pacman", "zypper", "apk"
    ]
    os_name = platform.system()
    if os_name == "Darwin":
        if shutil.which("brew"):
            if program == "wget2":
                return ["brew","install","wget2"]
            if program == "docker":
                return ["brew","install","--cask","docker"]
        return None
    if os_name == "Linux":
        for mgr in mgrs_linux:
            if not shutil.which(mgr):
                continue
            if program == "wget2":
                if mgr in ("apt-get","apt"):
                    return ["sudo", mgr, "install", "-y", "wget2"]
                if mgr in ("dnf","yum"):
                    return ["sudo", mgr, "install", "-y", "wget2"]
                if mgr == "pacman":
                    return ["sudo","pacman","-S","--noconfirm","wget2"]
                if mgr == "zypper":
                    return ["sudo","zypper","install","-y","wget2"]
                if mgr == "apk":
                    return ["sudo","apk","add","wget2"]
            if program == "docker":
                if mgr in ("apt-get","apt"):
                    return ["sudo", mgr, "install", "-y", "docker.io"]
                if mgr in ("dnf","yum"):
                    return ["sudo", mgr, "install", "-y", "docker"]
                if mgr == "pacman":
                    return ["sudo","pacman","-S","--noconfirm","docker"]
                if mgr == "zypper":
                    return ["sudo","zypper","install","-y","docker"]
                if mgr == "apk":
                    return ["sudo","apk","add","docker"]
        return None
    if os_name == "Windows":
        # Best effort: try winget or choco; package IDs may vary per system.
        if shutil.which("winget"):
            if program == "wget2":
                return ["winget","install","-e","--id","GnuWin32.Wget2"]
            if program == "docker":
                return ["winget","install","-e","--id","Docker.DockerDesktop"]
        if shutil.which("choco"):
            if program == "wget2":
                return ["choco","install","wget2","-y"]
            if program == "docker":
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

# ---------- headless CLI ----------
def headless_main(argv: list[str]) -> int:
    import argparse
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

    args = parser.parse_args(argv)

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

    print('[clone] Running wget2...')
    rc = _cli_run_stream(wget_cmd)
    if rc != 0:
        print(f"[error] wget2 exited with code {rc}")
        return rc
    print('[clone] Complete.')

    # Prepare Dockerfile & nginx.conf
    site_root = find_site_root(output_folder)
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
    if args.build:
        if not docker_available():
            print('[warn] Docker not installed. Skipping build.')
        else:
            print(f"[build] docker build -t {image} {output_folder}")
            rc = _cli_run_stream(['docker','build','-t', image, output_folder])
            docker_success = (rc == 0)
            if not docker_success:
                print('[error] Docker build failed.')

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
if __name__ == '__main__' and '--headless' in sys.argv:
    argv = [a for a in sys.argv[1:] if a != '--headless']
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
    QFileDialog, QTextEdit, QCheckBox, QComboBox, QSpinBox, QInputDialog, QFrame, QGraphicsDropShadowEffect, QSizePolicy,
    QMessageBox, QScrollArea, QLayout, QDialog, QProgressBar, QSplitter
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

# ---------- clone/build worker ----------
class CloneThread(QThread):
    progress = Signal(str)
    total_progress = Signal(int, str)  # (percent, phase)
    finished = Signal(str, bool, bool)  # (log, docker_build_success, clone_success)

    def __init__(self, url, docker_name, save_path, build_docker,
                 host_port=8080, size_cap=None, throttle=None, host_ip="127.0.0.1",
                 container_port=80, http_user=None, http_password=None,
                 pre_existing_count=0, pre_partial_count=0,
                 estimate_first=False, parallel_jobs=1,
                 disable_js=False,
                 cookies_file: str | None = None):
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

        def log_msg(m): log.append(m); self.progress.emit(m)

        # init overall progress tracking
        self._phase_pct = {"clone": 0, "build": 0, "cleanup": 0}
        if self.build_docker:
            weights = {"clone": 0.6, "build": 0.35, "cleanup": 0.05}
        else:
            weights = {"clone": 0.9, "build": 0.0, "cleanup": 0.1}
        total_w = sum(weights.values()) or 1.0
        self._weights = {k: (v / total_w) for k, v in weights.items()}

        def emit_total(phase, pct):
            try:
                pct = max(0, min(100, int(pct)))
            except Exception:
                pct = 0
            self._phase_pct[phase] = pct
            total = int(round(
                self._phase_pct["clone"] * self._weights["clone"] +
                self._phase_pct["build"] * self._weights["build"] +
                self._phase_pct["cleanup"] * self._weights["cleanup"]
            ))
            self.total_progress.emit(total, phase)

        if not is_wget2_available():
            log_msg("Error: wget2 is not installed. Please install it and try again.")
            self.finished.emit("\n".join(log), docker_success, clone_success); return

        output_folder = os.path.join(self.save_path, self.docker_name if self.docker_name else "site")
        # Do not delete existing folder; allow resuming and skipping already-downloaded files
        os.makedirs(output_folder, exist_ok=True)

        log_msg(f"Cloning {self.url} into {output_folder}")
        # Optional estimate prepass
        if self.estimate_first and not self._stop_requested:
            try:
                est = self._estimate_with_spider(self.url)
                if est > 0:
                    self.progress.emit(f"Estimated items to fetch: ~{est}")
                else:
                    self.progress.emit("Estimate: could not determine item count (proceeding)")
            except Exception as e:
                self.progress.emit(f"Estimate failed: {e} (proceeding)")
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
            self.progress.emit(f"Using wget2 with {self.parallel_jobs} parallel jobs.")
        if self.size_cap: wget_cmd += ["--quota", human_quota_suffix(self.size_cap)]
        if self.throttle: wget_cmd += ["--limit-rate", human_rate_suffix(self.throttle)]
        if self.http_user:
            wget_cmd += ["--http-user", self.http_user]
            # note: passing password on CLI can expose it to other users via process list
            if self.http_password is not None:
                wget_cmd += ["--http-password", self.http_password]
            self.progress.emit("Using HTTP authentication for cloning (credentials not shown).")

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
                self.progress.emit(
                    f"Files: existing before={self.pre_existing_count}, partial before={self.pre_partial_count}, new downloaded={new_files}"
                )
            except Exception:
                pass
        except Exception as e:
            log_msg(f"Error running wget2: {e}")
            self.finished.emit("\n".join(log), docker_success, clone_success); return

        if self._stop_requested:
            log_msg("Clone canceled by user.")
            self.finished.emit("\n".join(log), docker_success, clone_success); return

        site_root = find_site_root(output_folder)
        # Optionally strip scripts from HTML to prevent JS execution
        if self.disable_js:
            try:
                scanned, stripped = self._strip_js_from_html(site_root)
                log_msg(f"JavaScript disabled: stripped <script> tags from {stripped}/{scanned} HTML files.")
            except Exception as e:
                log_msg(f"Warning: failed to strip JS: {e}")
        rel_root = os.path.relpath(site_root, output_folder)
        log_msg(f"Site root detected: {rel_root}")

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
        log_msg("Dockerfile created.")

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
        log_msg("nginx.conf created.")

        # Optional docker build with cleanup after success
        if self.build_docker and not self._stop_requested:
            if not self.docker_name:
                log_msg("Skipping build: Docker image name is required when 'Build image' is checked.")
            elif docker_available():
                try:
                    log_msg("Building Docker image (0%)...")
                    emit_total("build", 0)
                    if self._run_docker_build_with_progress(output_folder, self.docker_name, emit_total):
                        docker_success = True
                        log_msg("Docker build complete (100%). Cleaning up build inputs...")
                        emit_total("build", 100)
                        self._cleanup_with_progress(output_folder, emit_total, keep_rel_root=rel_root)
                    else:
                        log_msg(f"Install Docker with:\n{docker_install_instructions()}")
                except Exception as e:
                    log_msg(f"Error building Docker image: {e}")
            else:
                log_msg("Docker not installed.")
                log_msg(f"Install with:\n{docker_install_instructions()}")

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
            for line in proc.stdout:
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

    def _cleanup_with_progress(self, output_folder: str, emit_total_cb, keep_rel_root: str = None):
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

# ---------- GUI (Dark gray/blue, regrouped sections) ----------
# Bring in Qt now that headless path has had a chance to exit
def build_dark_css(scale: float = 1.0) -> str:
    sf = max(0.7, min(1.5, float(scale or 1.0)))
    fs_base = int(round(13 * sf))
    fs_title = int(round(14 * sf))
    fs_section = int(round(15 * sf))
    rad_inp = max(6, int(round(10 * sf)))
    pad_v = max(3, int(round(6 * sf)))
    pad_h = max(4, int(round(8 * sf)))
    rad_btn = max(8, int(round(12 * sf)))
    rad_card = max(10, int(round(18 * sf)))
    pad_status = max(6, int(round(8 * sf)))
    return f"""
QWidget {{ color: #E6EDF3; font-size: {fs_base}px; }}
QWidget {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                      stop:0 #0e1621, stop:0.6 #152233, stop:1 #1b2a3c); }}

/* Inputs */
QLineEdit, QTextEdit, QSpinBox, QComboBox {{
    background-color: rgba(40, 52, 70, 190);
    border: 1px solid rgba(120, 140, 170, 160);
    border-radius: {rad_inp}px;
    padding: {pad_v}px {pad_h}px;
    color: #E6EDF3;
}}
QTextEdit {{ selection-background-color: rgba(120,140,170,180); }}

/* Buttons */
QPushButton {{
    background-color: #486a97;
    border: 1px solid #6789b3;
    border-radius: {rad_btn}px;
    padding: {pad_v+2}px {pad_h+2}px;
    color: #E6EDF3;
}}
QPushButton#primaryBtn {{ background-color: #4e78b8; border-color: #6b93cf; }}
QPushButton#ghostBtn {{
    background-color: rgba(78,120,184,0.15);
    border-color: rgba(107,147,207,0.25);
}}
QPushButton#dangerBtn {{ background-color: #b85555; border-color: #d27a7a; }}
QPushButton:disabled {{
    background-color: rgba(72,106,151,90);
    border-color: rgba(103,137,179,90);
    color: rgba(230, 237, 243, 120);
}}

/* Titles and panel */
QLabel[role="title"] {{ color: #C9D7EC; font-size: {fs_title}px; margin-top: {max(2,int(6*sf))}px; margin-bottom: {max(1,int(2*sf))}px; }}
QLabel[role="section"] {{ color: #AEC3E8; font-size: {fs_section}px; font-weight: 600; margin-top: {max(4,int(8*sf))}px; }}
QFrame#card {{
    background-color: rgba(28, 38, 52, 210);
    border-radius: {rad_card}px;
    border: 1px solid rgba(120, 140, 170, 120);
}}

/* Divider */
QFrame#divider {{
    background-color: rgba(120, 140, 170, 90);
    min-height: 1px; max-height: 1px; border: none;
}}

/* Status pill */
QLabel#status {{
    background-color: rgba(40, 50, 65, 220);
    border-radius: 12px;
    border: 1px solid rgba(120, 140, 170, 120);
    padding: {pad_status}px;
    color: #E6EDF3;
}}
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
        lines = []
        try:
            for line in proc.stdout:
                if not line:
                    continue
                lines.append(line.rstrip())
                self.progress.emit(line.rstrip())
            proc.wait()
        except Exception as e:
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
        self.settings = QSettings("CloneWebsiteDockerTool", "CW2DT")
        # Automatic UI scale based on available screen size (no manual control)
        self.ui_scale = self._compute_auto_scale()
        self.setStyleSheet(build_dark_css(self.ui_scale))

        # Outer layout
        root = QVBoxLayout(self)
        self._set_scaled_margins(root, 16, 16, 16, 16)
        root.setSpacing(int(14 * self.ui_scale))

        # Card
        self.card = QFrame()
        self.card.setObjectName("card")
        card_shadow = QGraphicsDropShadowEffect(self.card)
        card_shadow.setBlurRadius(24); card_shadow.setOffset(0, 8); card_shadow.setColor(Qt.GlobalColor.black)
        self.card.setGraphicsEffect(card_shadow)

        card_layout = QVBoxLayout(self.card)
        self._set_scaled_margins(card_layout, 18, 18, 18, 18)
        card_layout.setSpacing(int(12 * self.ui_scale))
        # Wrap in a scroll area so smaller screens can still access all controls
        self.scroll_area = QScrollArea(); self.scroll_area.setWidget(self.card); self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        # Main split: left = scroll area (controls), right = console panel
        self.right_panel = QFrame(); self.right_panel.setObjectName("rightPanel")
        self.right_panel.setMinimumWidth(320)
        self.right_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.right_col = QVBoxLayout(self.right_panel); self.right_col.setContentsMargins(12,0,0,0); self.right_col.setSpacing(int(10 * self.ui_scale))

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.scroll_area)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        root.addWidget(self.splitter)
        # Ensure left side fits content: prevent squeezing below content width
        try:
            min_left = self.card.sizeHint().width() + 24
            self.scroll_area.setMinimumWidth(min_left)
        except Exception:
            pass

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

        # ---------- DEPENDENCIES ----------
        self.deps_frame = QFrame(); deps = QHBoxLayout(self.deps_frame); deps.setContentsMargins(0,0,0,0)
        self.dep_wget2_label = QLabel("")
        self.install_wget2_btn = QPushButton("Copy wget2 install cmd"); self.install_wget2_btn.setObjectName("ghostBtn"); self.install_wget2_btn.clicked.connect(self.copy_wget2_install_cmd)
        self.wget2_docs_btn = QPushButton("Open wget2 docs"); self.wget2_docs_btn.setObjectName("ghostBtn"); self.wget2_docs_btn.clicked.connect(self.open_wget2_docs)
        self.dep_docker_label = QLabel("")
        self.install_docker_btn = QPushButton("Copy Docker install cmd"); self.install_docker_btn.setObjectName("ghostBtn"); self.install_docker_btn.clicked.connect(self.copy_docker_install_cmd)
        self.docker_docs_btn = QPushButton("Open Docker docs"); self.docker_docs_btn.setObjectName("ghostBtn"); self.docker_docs_btn.clicked.connect(self.open_docker_docs)
        deps.addWidget(self.dep_wget2_label); deps.addWidget(self.install_wget2_btn); deps.addWidget(self.wget2_docs_btn); deps.addSpacing(12)
        deps.addWidget(self.dep_docker_label); deps.addWidget(self.install_docker_btn); deps.addWidget(self.docker_docs_btn); deps.addSpacing(12)
        deps.addStretch(1)
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
        dest_row.addWidget(self.save_path_display, 1); dest_row.addWidget(browse_btn, 0)
        source_grid.addWidget(self.lbl_dest, 1, 0); source_grid.addLayout(dest_row, 1, 1, 1, 2)
        card_layout.addLayout(source_grid)

        # ---------- BUILD (collapsible) ----------
        build_grid = QGridLayout(); build_grid.setHorizontalSpacing(10); build_grid.setVerticalSpacing(8)
        self.build_checkbox = QCheckBox("Build Docker image after clone")
        build_grid.addWidget(self.build_checkbox, 0, 0, 1, 3)

        self.lbl_img = QLabel("Docker Image Name:"); self.lbl_img.setProperty("role", "title")
        self.docker_name_input = QLineEdit(); self.docker_name_input.textChanged.connect(self.refresh_run_buttons)
        build_grid.addWidget(self.lbl_img, 1, 0); build_grid.addWidget(self.docker_name_input, 1, 1, 1, 2)

        self.size_frame = QFrame(); sz = QHBoxLayout(self.size_frame); sz.setContentsMargins(0,0,0,0)
        self.size_cap_checkbox = QCheckBox("Limit download size")
        self.size_cap_value = QSpinBox(); self.size_cap_value.setRange(1,1_000_000); self.size_cap_value.setValue(200)
        self.size_cap_unit = QComboBox(); self.size_cap_unit.addItems(["MB","GB","TB"])
        self.size_cap_value.setEnabled(False); self.size_cap_unit.setEnabled(False)
        self.size_cap_checkbox.stateChanged.connect(lambda: self.size_cap_value.setEnabled(self.size_cap_checkbox.isChecked()))
        self.size_cap_checkbox.stateChanged.connect(lambda: self.size_cap_unit.setEnabled(self.size_cap_checkbox.isChecked()))
        sz.addWidget(self.size_cap_checkbox); sz.addSpacing(6); sz.addWidget(self.size_cap_value); sz.addWidget(self.size_cap_unit)
        build_grid.addWidget(self.size_frame, 2, 0, 1, 3)

        self.throttle_frame = QFrame(); th = QHBoxLayout(self.throttle_frame); th.setContentsMargins(0,0,0,0)
        self.throttle_checkbox = QCheckBox("Throttle download speed")
        self.throttle_value = QSpinBox(); self.throttle_value.setRange(1,1_000_000); self.throttle_value.setValue(1024)
        self.throttle_unit = QComboBox(); self.throttle_unit.addItems(["KB/s","MB/s"])
        self.throttle_value.setEnabled(False); self.throttle_unit.setEnabled(False)
        self.throttle_checkbox.stateChanged.connect(lambda: self.throttle_value.setEnabled(self.throttle_checkbox.isChecked()))
        self.throttle_checkbox.stateChanged.connect(lambda: self.throttle_unit.setEnabled(self.throttle_checkbox.isChecked()))
        th.addWidget(self.throttle_checkbox); th.addSpacing(6); th.addWidget(self.throttle_value); th.addWidget(self.throttle_unit)
        build_grid.addWidget(self.throttle_frame, 3, 0, 1, 3)

        build_container = QWidget(); build_container.setLayout(build_grid)
        self.build_section = CollapsibleSection("Build", start_collapsed=False)
        self.build_section.setContentLayout(build_grid)
        card_layout.addWidget(self.build_section)

        # ---------- ADVANCED (collapsible) ----------
        self.auth_frame = QFrame(); au = QHBoxLayout(self.auth_frame); au.setContentsMargins(0,0,0,0)
        self.auth_checkbox = QCheckBox("Use HTTP authentication")
        self.auth_checkbox.setToolTip(
            "Warning: Providing username/password passes them to wget2 via the command line, "
            "which may be visible to other local users via process listings. "
            "For stricter security, consider using a temporary .wgetrc/.netrc file."
        )
        self.auth_user_input = QLineEdit(); self.auth_user_input.setPlaceholderText("Username")
        self.auth_pass_input = QLineEdit(); self.auth_pass_input.setPlaceholderText("Password"); self.auth_pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        for w in (self.auth_user_input, self.auth_pass_input):
            w.setEnabled(False)
        self.auth_checkbox.stateChanged.connect(lambda: self.auth_user_input.setEnabled(self.auth_checkbox.isChecked()))
        self.auth_checkbox.stateChanged.connect(lambda: self.auth_pass_input.setEnabled(self.auth_checkbox.isChecked()))
        au.addWidget(self.auth_checkbox); au.addSpacing(6); au.addWidget(self.auth_user_input); au.addWidget(self.auth_pass_input)
        adv_grid = QGridLayout(); adv_grid.setHorizontalSpacing(10); adv_grid.setVerticalSpacing(8)
        adv_grid.addWidget(self.auth_frame, 0, 0, 1, 3)

        # Estimation + Parallelism (Advanced)
        self.estimate_frame = QFrame(); ef = QHBoxLayout(self.estimate_frame); ef.setContentsMargins(0,0,0,0)
        self.estimate_checkbox = QCheckBox("Estimate files before clone"); self.estimate_checkbox.setChecked(True)
        self.parallel_checkbox = QCheckBox("Enable parallel downloads"); self.parallel_checkbox.setChecked(True)
        self.parallel_label = QLabel("Parallel jobs:"); self.parallel_label.setProperty("role", "title")
        self.parallel_jobs_input = QSpinBox(); self.parallel_jobs_input.setRange(1, 64); self.parallel_jobs_input.setValue(self.default_parallel_jobs)
        # enable/disable spinner by checkbox
        self.parallel_jobs_input.setEnabled(self.parallel_checkbox.isChecked())
        self.parallel_checkbox.stateChanged.connect(lambda: self.parallel_jobs_input.setEnabled(self.parallel_checkbox.isChecked()))
        self.disable_js_checkbox = QCheckBox("Disable JavaScript (strip scripts + CSP)"); self.disable_js_checkbox.setChecked(False)
        ef.addWidget(self.disable_js_checkbox); ef.addSpacing(12)
        ef.addWidget(self.estimate_checkbox); ef.addSpacing(12)
        ef.addWidget(self.parallel_checkbox); ef.addSpacing(8)
        ef.addWidget(self.parallel_label); ef.addWidget(self.parallel_jobs_input); ef.addStretch(1)
        adv_grid.addWidget(self.estimate_frame, 1, 0, 1, 3)

        # Cookie import row
        self.cookies_row = QHBoxLayout(); self.cookies_row.setContentsMargins(0,0,0,0)
        self.scan_cookies_btn = QPushButton("Scan Browser Cookies"); self.scan_cookies_btn.setObjectName("ghostBtn")
        self.scan_cookies_btn.setToolTip("Search common browser profiles for cookies matching the current URL and import them for authenticated requests.")
        self.scan_cookies_btn.clicked.connect(self.scan_browser_cookies)
        self.use_cookies_checkbox = QCheckBox("Use imported cookies")
        self.use_cookies_checkbox.setChecked(False); self.use_cookies_checkbox.setEnabled(False)
        self.cookies_status = QLabel("No cookies imported")
        self.cookies_row.addWidget(self.scan_cookies_btn)
        self.cookies_row.addSpacing(8)
        self.cookies_row.addWidget(self.use_cookies_checkbox)
        self.cookies_row.addSpacing(12)
        self.cookies_row.addWidget(self.cookies_status)
        self.cookies_row.addStretch(1)
        adv_grid.addLayout(self.cookies_row, 2, 0, 1, 3)
        self.adv_section = CollapsibleSection("Advanced Options", start_collapsed=True)
        self.adv_section.setContentLayout(adv_grid)
        card_layout.addWidget(self.adv_section)

        # ---------- RUN (collapsible, but keep action buttons outside) ----------
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

        run_grid.addLayout(ip_row,       0, 0, 1, 3)
        run_grid.addLayout(host_port_row,1, 0, 1, 3)
        run_grid.addLayout(cont_port_row,2, 0, 1, 3)

        # Actions row (kept outside the collapsible Run section)
        actions_row = QHBoxLayout()
        self.clone_btn = QPushButton("Clone  Prepare"); self.clone_btn.setObjectName("primaryBtn"); self.clone_btn.clicked.connect(self.start_clone)
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
        if not docker_available(): self.run_created_btn.setToolTip(f"Docker not found. Install:\n{docker_install_instructions()}")
        self.run_created_btn.clicked.connect(self.run_created_container)
        actions_row.addWidget(self.run_created_btn)

        self.run_folder_btn = QPushButton("Serve From Folder (no build)"); self.run_folder_btn.setObjectName("primaryBtn")
        self.run_folder_btn.setEnabled(False)
        if not docker_available(): self.run_folder_btn.setToolTip(f"Docker not found. Install:\n{docker_install_instructions()}")
        self.run_folder_btn.clicked.connect(self.run_from_folder)
        actions_row.addWidget(self.run_folder_btn)

        self.stop_btn = QPushButton("Stop Container"); self.stop_btn.setObjectName("dangerBtn")
        self.stop_btn.setEnabled(False); self.stop_btn.clicked.connect(self.stop_container)
        actions_row.addWidget(self.stop_btn)
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
        self.console = QTextEdit(); self.console.setReadOnly(True); self.console.setMinimumHeight(260)
        self.console.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.right_col.addWidget(self.console, 1)

        # Total progress (compact line)
        # (status bar carries total progress during tasks)

        # Divider above status bar
        root.addWidget(divider())
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
        status_shadow = QGraphicsDropShadowEffect(self.status_label); status_shadow.setBlurRadius(18); status_shadow.setOffset(0, 6); status_shadow.setColor(Qt.GlobalColor.black)
        self.status_label.setGraphicsEffect(status_shadow)
        root.addWidget(self.status_label)
        # Base status text used for appending progress
        self._status_base_text = "No container running"

        # timers & init
        self.status_timer = QTimer(); self.status_timer.timeout.connect(self.check_container_status); self.status_timer.start(3000)
        self.set_advanced_mode(False)
        self._align_label_column()
        self.refresh_run_buttons()
        # Load previous window geometry if available, then finalize sizing
        self._geometry_restored = self._load_window_settings()
        self._finalize_sizing()
        self.refresh_deps_panel()
        self.run_dependency_dialog_if_needed()
        # Load recents after settings available
        self._load_recent_urls()
        # Ensure left pane minimum width fits all content horizontally
        self._update_left_min_width()

    def _set_scaled_margins(self, layout: QLayout | None, left, top, right, bottom):
        if layout is None:
            return
        s = self.ui_scale
        layout.setContentsMargins(int(left*s), int(top*s), int(right*s), int(bottom*s))

    def _update_left_min_width(self):
        try:
            self.card.adjustSize()
            min_left = self.card.sizeHint().width() + int(24 * self.ui_scale)
            self.scroll_area.setMinimumWidth(min_left)
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
        self.setStyleSheet(build_dark_css(self.ui_scale))
        # Update key layout paddings
        root: QLayout = self.layout()
        if root:
            self._set_scaled_margins(root, 16, 16, 16, 16)
            root.setSpacing(int(14 * self.ui_scale))
        # Card layout margins
        if hasattr(self, 'card') and self.card.layout():
            self._set_scaled_margins(self.card.layout(), 18, 18, 18, 18)
            self.card.layout().setSpacing(int(12 * self.ui_scale))
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

    # ----- advanced toggle -----
    def set_advanced_mode(self, enabled: bool):
        # Collapsible section controls visibility; no-op kept for backward compatibility
        return

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
        if not getattr(self, "_geometry_restored", False):
            self.resize(w, h)

    def _load_window_settings(self) -> bool:
        try:
            geom = self.settings.value("geometry")
            if geom is not None:
                self.restoreGeometry(geom)
                return True
        except Exception:
            pass
        return False

    def closeEvent(self, event):
        try:
            self.settings.setValue("geometry", self.saveGeometry())
        except Exception:
            pass
        super().closeEvent(event)

    # ----- recents -----
    def _load_recent_urls(self):
        items = []
        try:
            val = self.settings.value("recent_urls", [])
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
        if self.container_id is not None:
            self.console.append("Stop the running container before creating a new one."); return

        try:
            url = self.url_input.currentText().strip()
        except Exception:
            # fallback if widget type changes
            url = str(getattr(self.url_input, 'text', lambda: '')()).strip()
        docker_name = self.docker_name_input.text().strip()
        save_path = self.save_path_display.text().strip()
        self.current_port = self.port_input.value()  # host
        self.current_container_port = self.cport_input.value()  # container
        ip_text = normalize_ip(self.bind_ip_input.text())

        if not url or not save_path:
            self.console.append("Website URL and Destination Folder are required."); return
        if not ip_text:
            self.console.append("Invalid Bind IP. Use 127.0.0.1, 0.0.0.0, localhost, or a valid IPv4."); return

        self.current_host_ip = ip_text

        project_dir_name = docker_name if docker_name else "site"
        self.last_project_dir = os.path.abspath(os.path.join(save_path, project_dir_name))
        self.update_status(False, cid=None)

        # Indicate resume if output dir already has content, and count files
        try:
            resume = os.path.isdir(self.last_project_dir) and any(True for _ in os.scandir(self.last_project_dir))
        except Exception:
            resume = False
        pre_existing, pre_partial = (0, 0)
        if resume:
            pre_existing, pre_partial = count_files_and_partials(self.last_project_dir)
            self.resuming_label.setText(f"Cloning (resuming) • Existing: {pre_existing} • Partial: {pre_partial}")
            self.resuming_label.setVisible(True)
            self.console.append(f"Existing files detected: {pre_existing} • partial: {pre_partial}")
        else:
            self.resuming_label.setVisible(False)

        if port_in_use(self.current_host_ip, self.current_port):
            self.console.append(f"Port {self.current_port} appears in use on {self.current_host_ip}.")
            default = max(1, min(65535, self.current_port + 1))
            port, ok = QInputDialog.getInt(self, "Port in Use", "Enter a different port:", default, 1, 65535)
            if not ok: return
            self.current_port = port
            self.port_input.setValue(port)

        size_cap = None
        if self.size_cap_checkbox.isChecked():
            mul = {"MB":1024**2,"GB":1024**3,"TB":1024**4}[self.size_cap_unit.currentText()]
            size_cap = self.size_cap_value.value() * mul
        throttle = None
        if self.throttle_checkbox.isChecked():
            mul = 1024 if self.throttle_unit.currentText()=="KB/s" else 1024**2
            throttle = self.throttle_value.value() * mul

        http_user = None; http_password = None
        if self.auth_checkbox.isChecked():
            http_user = self.auth_user_input.text().strip()
            http_password = self.auth_pass_input.text()
            if http_user and not http_password:
                # allow empty password, but inform user
                self.console.append("HTTP auth username provided; password is empty.")

        # Advanced flags rely on individual control values regardless of collapse state
        estimate_first = self.estimate_checkbox.isChecked()
        parallel_jobs = self.parallel_jobs_input.value() if self.parallel_checkbox.isChecked() else 1
        disable_js = self.disable_js_checkbox.isChecked()

        if self.build_checkbox.isChecked() and not docker_name:
            self.console.append("Docker image name is required when building an image."); return

        self.console.clear()
        # Informational note about estimation and parallelism defaults/overrides
        if estimate_first:
            self.console.append("Estimation prepass: enabled")
        else:
            self.console.append("Estimation prepass: disabled")
        src = "enabled" if self.parallel_checkbox.isChecked() else "disabled"
        if parallel_jobs > 1:
            self.console.append(f"Parallel downloads: enabled • jobs={parallel_jobs} ({src})")
        else:
            self.console.append(f"Parallel downloads: disabled ({src})")
        worker = CloneThread(
            url, project_dir_name, save_path,
            self.build_checkbox.isChecked(),
            host_port=self.current_port, size_cap=size_cap, throttle=throttle,
            host_ip=self.current_host_ip, container_port=self.current_container_port,
            http_user=http_user, http_password=http_password,
            pre_existing_count=pre_existing, pre_partial_count=pre_partial,
            estimate_first=estimate_first, parallel_jobs=parallel_jobs,
            disable_js=disable_js,
            cookies_file=getattr(self, 'imported_cookies_file', None) if self.use_cookies_checkbox.isChecked() else None
        )
        self.clone_thread = worker
        worker.progress.connect(self.update_console)
        worker.total_progress.connect(self.update_total_progress)
        worker.finished.connect(self.clone_finished)
        # status bar will show progress during tasks
        # Disable clone button during operation to prevent double-starts
        self.clone_btn.setEnabled(False)
        self.cancel_clone_btn.setEnabled(True)
        self.last_clone_failed_or_canceled = False
        # Remember URL in recents
        if url:
            self._remember_recent_url(url)
        worker.start()

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
        self.deps_frame.setVisible(not (has_wget2 and has_docker))
        self.dep_wget2_label.setText("wget2: Installed" if has_wget2 else "wget2: Missing")
        self.dep_docker_label.setText("Docker: Installed" if has_docker else "Docker: Missing")
        self.install_wget2_btn.setEnabled(not has_wget2)
        self.wget2_docs_btn.setEnabled(True)
        self.install_docker_btn.setEnabled(not has_docker)
        self.docker_docs_btn.setEnabled(True)

    def run_dependency_dialog_if_needed(self):
        """Hard-gate required dependencies (wget2, browser_cookie3). Blocks UI until resolved or Quit."""
        def deps_missing():
            missing = []
            if not is_wget2_available():
                missing.append(('wget2', get_install_cmd('wget2')))
            try:
                importlib.import_module('browser_cookie3');
            except Exception:
                missing.append(('browser_cookie3', [sys.executable, '-m', 'pip', 'install', 'browser_cookie3']))
            return missing

        self.set_controls_enabled(False)
        while True:
            missing = deps_missing()
            if not missing:
                self.set_controls_enabled(True)
                self.refresh_deps_panel()
                return

            dlg = QDialog(self); dlg.setWindowTitle('Installing Dependencies')
            v = QVBoxLayout(dlg)
            v.addWidget(QLabel('Installing required dependencies...'))
            bar = QProgressBar(); bar.setRange(0, len(missing)); bar.setValue(0); v.addWidget(bar)
            log = QTextEdit(); log.setReadOnly(True); log.setMinimumHeight(180); v.addWidget(log)

            def append(text):
                log.append(text); log.ensureCursorVisible()

            completed = 0
            for name, cmd in missing:
                append(f"Installing {name}...")
                if not cmd:
                    append(f"No automatic install command for {name}. Please install manually.")
                    completed += 1; bar.setValue(completed)
                    continue
                th = InstallerThread(cmd)
                th.progress.connect(append)
                ok_holder = {'ok': False}
                th.finished_ok.connect(lambda ok, h=ok_holder: h.__setitem__('ok', ok))
                th.start()
                # Wait
                while th.isRunning():
                    QGuiApplication.processEvents()
                    QTimer.singleShot(50, lambda: None)
                completed += 1
                bar.setValue(completed)
                append((f"{name} installed successfully.\n") if ok_holder['ok'] else (f"Failed to install {name}. You may need to install it manually.\n"))

            # Done this pass
            dlg.accept()

            # Recheck
            still_missing = deps_missing()
            if not still_missing:
                self.set_controls_enabled(True)
                self.refresh_deps_panel()
                return

            # Offer options: Retry, Copy cmds, Open docs, Quit
            box = QMessageBox(self)
            box.setWindowTitle('Dependencies Missing')
            msg = 'Some required dependencies could not be installed automatically. Choose an option.'
            box.setText(msg)
            copy_btn = box.addButton('Copy install cmds', QMessageBox.ButtonRole.ActionRole)
            docs_btn = box.addButton('Open docs', QMessageBox.ButtonRole.ActionRole)
            retry_btn = box.addButton('Retry', QMessageBox.ButtonRole.AcceptRole)
            quit_btn = box.addButton('Quit', QMessageBox.ButtonRole.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked == quit_btn:
                QApplication.quit(); return
            if clicked == copy_btn:
                # Compose commands for all missing deps
                cmds = []
                for name, cmd in still_missing:
                    if name == 'wget2':
                        c = get_install_cmd('wget2'); cmds.append(' '.join(c) if c else 'See: https://gitlab.com/gnuwget/wget2#installation')
                    elif name == 'browser_cookie3':
                        cmds.append(f"{sys.executable} -m pip install browser_cookie3")
                QGuiApplication.clipboard().setText('\n'.join(cmds))
                self.console.append('Copied install commands to clipboard.')
            elif clicked == docs_btn:
                self.open_wget2_docs()
            # else retry -> loop

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

    # (legacy wget2 gate removed; dependency gating handled by run_dependency_dialog_if_needed)

    def clone_finished(self, log, docker_success, clone_success):
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

    def update_total_progress(self, percent: int, phase: str):
        phase_title = {
            "clone": "Cloning",
            "build": "Docker build",
            "cleanup": "Cleanup"
        }.get(phase, phase.title())
        # Show total progress in the status bar (spanning bottom), appended to base status
        base = getattr(self, '_status_base_text', '') or ''
        sep = " • " if base else ""
        self._set_status_text_elided(f"{base}{sep}Total progress: {percent}% • {phase_title}")

# ---------- main ----------
if __name__ == "__main__":
    if '--headless' in sys.argv:
        # Run CLI mode without creating a QApplication
        # Remove the flag to avoid confusion in argparse help
        argv = [a for a in sys.argv[1:] if a != '--headless']
        code = headless_main(argv)
        sys.exit(code)
    # GUI mode
    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass
    try:
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    except Exception:
        pass
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

    app = QApplication(sys.argv)
    icon_path = find_icon("icon.png")
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))
    window = DockerClonerGUI()
    window.show()
    sys.exit(app.exec())
