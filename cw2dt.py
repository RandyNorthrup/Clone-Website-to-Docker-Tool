import sys, os, subprocess, shutil, platform, socket, webbrowser, ipaddress
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QTextEdit, QCheckBox, QComboBox, QSpinBox, QInputDialog, QFrame, QGraphicsDropShadowEffect, QSizePolicy
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QGuiApplication, QFontMetrics, QPixmap, QIcon

# ---------- helpers ----------
def is_wget_available():
    try:
        subprocess.run(["wget", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False

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

# ---------- clone/build worker ----------
class CloneThread(QThread):
    progress = Signal(str)
    finished = Signal(str, bool)  # (log, docker_build_success)

    def __init__(self, url, docker_name, save_path, build_docker,
                 host_port=8080, size_cap=None, throttle=None, host_ip="127.0.0.1",
                 container_port=80):
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

    def run(self):
        log = []
        docker_success = False

        def log_msg(m): log.append(m); self.progress.emit(m)

        if not is_wget_available():
            log_msg("Error: wget is not installed. Install wget and try again.")
            self.finished.emit("\n".join(log), docker_success); return

        output_folder = os.path.join(self.save_path, self.docker_name if self.docker_name else "site")
        if os.path.exists(output_folder):
            shutil.rmtree(output_folder)
        os.makedirs(output_folder, exist_ok=True)

        log_msg(f"Cloning {self.url} into {output_folder}")
        wget_cmd = [
            "wget", "-e", "robots=off",
            "--mirror", "--convert-links", "--adjust-extension",
            "--page-requisites", "--no-parent",
            self.url, "-P", output_folder
        ]
        if self.size_cap: wget_cmd += ["--quota", human_quota_suffix(self.size_cap)]
        if self.throttle: wget_cmd += ["--limit-rate", human_rate_suffix(self.throttle)]

        try:
            result = subprocess.run(wget_cmd, capture_output=True, text=True)
            if result.stdout: log_msg(result.stdout)
            if result.returncode != 0:
                log_msg(f"Error cloning site: {result.stderr.strip()}")
                self.finished.emit("\n".join(log), docker_success); return
            log_msg("Cloning complete.")
        except Exception as e:
            log_msg(f"Error running wget: {e}")
            self.finished.emit("\n".join(log), docker_success); return

        site_root = find_site_root(output_folder)
        rel_root = os.path.relpath(site_root, output_folder)
        log_msg(f"Site root detected: {rel_root}")

        # Dockerfile & nginx.conf tuned to container_port
        dockerfile_path = os.path.join(output_folder, "Dockerfile")
        with open(dockerfile_path, "w", encoding="utf-8") as f:
            f.write(
                "FROM nginx:alpine\n"
                f"COPY {rel_root}/ /usr/share/nginx/html\n"
                f"EXPOSE {self.container_port}\n"
                "CMD [\"nginx\", \"-g\", \"daemon off;\"]\n"
            )
        log_msg("Dockerfile created.")

        nginx_conf_path = os.path.join(output_folder, "nginx.conf")
        with open(nginx_conf_path, "w", encoding="utf-8") as f:
            f.write(
                "server {\n"
                f"    listen {self.container_port};\n"
                "    server_name localhost;\n"
                "    root /usr/share/nginx/html;\n"
                "    index index.html;\n"
                "    location / { try_files $uri $uri/ =404; }\n"
                "}\n"
            )
        log_msg("nginx.conf created.")

        # Optional docker build with cleanup after success
        if self.build_docker:
            if not self.docker_name:
                log_msg("Skipping build: Docker image name is required when 'Build image' is checked.")
            elif docker_available():
                try:
                    log_msg("Building Docker image...")
                    result = subprocess.run(
                        ["docker", "build", "-t", self.docker_name, output_folder],
                        capture_output=True, text=True
                    )
                    if result.stdout: log_msg(result.stdout)
                    if result.returncode != 0:
                        log_msg(f"Docker build failed: {result.stderr.strip()}")
                        log_msg(f"Install Docker with:\n{docker_install_instructions()}")
                    else:
                        docker_success = True
                        log_msg("Docker build complete. Cleaning up build inputs...")
                        for item in os.listdir(output_folder):
                            path = os.path.join(output_folder, item)
                            try:
                                shutil.rmtree(path) if os.path.isdir(path) else os.unlink(path)
                            except Exception as e:
                                log_msg(f"Cleanup warning ({item}): {e}")
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
        with open(os.path.join(output_folder, f"README_{image_tag or 'site'}.md"), "w", encoding="utf-8") as f:
            f.write(
                f"# Docker Website Container\n\n"
                f"## Project Location\n{abs_output}\n\n"
                f"## Image Status\n"
                + (f"Built locally as: `{image_tag}` (check with `docker images`).\n\n"
                   if docker_success else
                   f"Not built yet. To build locally: `docker build -t {image_tag} .`\n\n")
                + "## How to Run\n"
                  f"- Run created container (if built):\n"
                  f"  ```bash\ndocker run -d -p {bind_ip_for_cmd}:{self.host_port}:{self.container_port} {image_tag}\n```\n"
                  f"- Serve directly from this folder (no build):\n"
                  f"  ```bash\n# create a temp nginx file that listens on your chosen container port\ncat > _folder.default.conf <<'CONF'\nserver {{\n    listen {self.container_port};\n    server_name localhost;\n    root /usr/share/nginx/html;\n    index index.html;\n    location / {{ try_files $uri $uri/ =404; }}\n}}\nCONF\n\ndocker run -d -p {bind_ip_for_cmd}:{self.host_port}:{self.container_port} \\\n  -v \"{abs_output}\":/usr/share/nginx/html \\\n  -v \"$(pwd)/_folder.default.conf\":/etc/nginx/conf.d/default.conf:ro \\\n  nginx:alpine\n```\n"
                  f"- Once running, open: http://{('localhost' if bind_ip_for_cmd=='0.0.0.0' else bind_ip_for_cmd)}:{self.host_port}\n"
            )
        log_msg("README created.")

        self.finished.emit("\n".join(log), docker_success)

# ---------- GUI (Dark gray/blue, regrouped sections) ----------
DARK_CSS = """
QWidget { color: #E6EDF3; font-size: 13px; }
QWidget { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                      stop:0 #0e1621, stop:0.6 #152233, stop:1 #1b2a3c); }

/* Inputs */
QLineEdit, QTextEdit, QSpinBox, QComboBox {
    background-color: rgba(40, 52, 70, 190);
    border: 1px solid rgba(120, 140, 170, 160);
    border-radius: 10px;
    padding: 6px 8px;
    color: #E6EDF3;
}
QTextEdit { selection-background-color: rgba(120,140,170,180); }

/* Buttons */
QPushButton {
    background-color: #486a97;
    border: 1px solid #6789b3;
    border-radius: 12px;
    padding: 8px 12px;
    color: #E6EDF3;
}
QPushButton#primaryBtn { background-color: #4e78b8; border-color: #6b93cf; }
QPushButton#ghostBtn {
    background-color: rgba(78,120,184,0.15);
    border-color: rgba(107,147,207,0.25);
}
QPushButton#dangerBtn { background-color: #b85555; border-color: #d27a7a; }
QPushButton:disabled {
    background-color: rgba(72,106,151,90);
    border-color: rgba(103,137,179,90);
    color: rgba(230, 237, 243, 120);
}

/* Titles and panel */
QLabel[role="title"] { color: #C9D7EC; font-size: 14px; margin-top: 6px; margin-bottom: 2px; }
QLabel[role="section"] { color: #AEC3E8; font-size: 15px; font-weight: 600; margin-top: 8px; }
QFrame#card {
    background-color: rgba(28, 38, 52, 210);
    border-radius: 18px;
    border: 1px solid rgba(120, 140, 170, 120);
}

/* Divider */
QFrame#divider {
    background-color: rgba(120, 140, 170, 90);
    min-height: 1px; max-height: 1px; border: none;
}

/* Status pill */
QLabel#status {
    background-color: rgba(40, 50, 65, 220);
    border-radius: 12px;
    border: 1px solid rgba(120, 140, 170, 120);
    padding: 8px;
    color: #E6EDF3;
}
"""

class DockerClonerGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Clone Website to Docker Tool")
        self.setGeometry(100, 100, 940, 960)

        # --- State ---
        self.container_id = None
        self.container_url = None
        self.container_start_time = None
        self.current_port = 8080              # host port
        self.current_container_port = 80      # container port (mapped)
        self.current_host_ip = "127.0.0.1"
        self.last_project_dir = None

        self.setStyleSheet(DARK_CSS)

        # Outer layout
        root = QVBoxLayout(self); root.setContentsMargins(16, 16, 16, 16); root.setSpacing(14)

        # Card
        self.card = QFrame()
        self.card.setObjectName("card")
        card_shadow = QGraphicsDropShadowEffect(self.card)
        card_shadow.setBlurRadius(24); card_shadow.setOffset(0, 8); card_shadow.setColor(Qt.GlobalColor.black)
        self.card.setGraphicsEffect(card_shadow)

        card_layout = QVBoxLayout(self.card); card_layout.setContentsMargins(18, 18, 18, 18); card_layout.setSpacing(12)
        root.addWidget(self.card)

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

        # ---------- SOURCE ----------
        lbl_source = QLabel("Source"); lbl_source.setProperty("role", "section")
        card_layout.addWidget(lbl_source)
        card_layout.addWidget(divider())

        source_grid = QGridLayout(); source_grid.setHorizontalSpacing(10); source_grid.setVerticalSpacing(8)
        self.lbl_url  = QLabel("Website URL:"); self.lbl_url.setProperty("role", "title")
        self.url_input = QLineEdit()
        source_grid.addWidget(self.lbl_url, 0, 0); source_grid.addWidget(self.url_input, 0, 1, 1, 2)

        self.lbl_dest = QLabel("Destination Folder:"); self.lbl_dest.setProperty("role", "title")
        dest_row = QHBoxLayout()
        self.save_path_display = QLineEdit(); self.save_path_display.setReadOnly(True)
        browse_btn = QPushButton("Browse"); browse_btn.setObjectName("ghostBtn"); browse_btn.clicked.connect(self.browse_folder)
        dest_row.addWidget(self.save_path_display, 1); dest_row.addWidget(browse_btn, 0)
        source_grid.addWidget(self.lbl_dest, 1, 0); source_grid.addLayout(dest_row, 1, 1, 1, 2)
        card_layout.addLayout(source_grid)

        # ---------- BUILD ----------
        lbl_build = QLabel("Build"); lbl_build.setProperty("role", "section")
        card_layout.addWidget(lbl_build); card_layout.addWidget(divider())

        build_grid = QGridLayout(); build_grid.setHorizontalSpacing(10); build_grid.setVerticalSpacing(8)
        self.build_checkbox = QCheckBox("Build Docker image after clone")
        build_grid.addWidget(self.build_checkbox, 0, 0, 1, 3)

        self.lbl_img = QLabel("Docker Image Name:"); self.lbl_img.setProperty("role", "title")
        self.docker_name_input = QLineEdit(); self.docker_name_input.textChanged.connect(self.refresh_run_buttons)
        build_grid.addWidget(self.lbl_img, 1, 0); build_grid.addWidget(self.docker_name_input, 1, 1, 1, 2)

        adv_row = QHBoxLayout()
        self.adv_toggle = QCheckBox("Advanced Options"); self.adv_toggle.setToolTip("Show/hide size limit and download throttle")
        self.adv_toggle.stateChanged.connect(lambda: self.set_advanced_mode(self.adv_toggle.isChecked()))
        adv_row.addWidget(self.adv_toggle); adv_row.addStretch(1)
        build_grid.addLayout(adv_row, 2, 0, 1, 3)

        self.size_frame = QFrame(); sz = QHBoxLayout(self.size_frame); sz.setContentsMargins(0,0,0,0)
        self.size_cap_checkbox = QCheckBox("Limit download size")
        self.size_cap_value = QSpinBox(); self.size_cap_value.setRange(1,1_000_000); self.size_cap_value.setValue(200)
        self.size_cap_unit = QComboBox(); self.size_cap_unit.addItems(["MB","GB","TB"])
        self.size_cap_value.setEnabled(False); self.size_cap_unit.setEnabled(False)
        self.size_cap_checkbox.stateChanged.connect(lambda: self.size_cap_value.setEnabled(self.size_cap_checkbox.isChecked()))
        self.size_cap_checkbox.stateChanged.connect(lambda: self.size_cap_unit.setEnabled(self.size_cap_checkbox.isChecked()))
        sz.addWidget(self.size_cap_checkbox); sz.addSpacing(6); sz.addWidget(self.size_cap_value); sz.addWidget(self.size_cap_unit)
        build_grid.addWidget(self.size_frame, 3, 0, 1, 3)

        self.throttle_frame = QFrame(); th = QHBoxLayout(self.throttle_frame); th.setContentsMargins(0,0,0,0)
        self.throttle_checkbox = QCheckBox("Throttle download speed")
        self.throttle_value = QSpinBox(); self.throttle_value.setRange(1,1_000_000); self.throttle_value.setValue(1024)
        self.throttle_unit = QComboBox(); self.throttle_unit.addItems(["KB/s","MB/s"])
        self.throttle_value.setEnabled(False); self.throttle_unit.setEnabled(False)
        self.throttle_checkbox.stateChanged.connect(lambda: self.throttle_value.setEnabled(self.throttle_checkbox.isChecked()))
        self.throttle_checkbox.stateChanged.connect(lambda: self.throttle_unit.setEnabled(self.throttle_checkbox.isChecked()))
        th.addWidget(self.throttle_checkbox); th.addSpacing(6); th.addWidget(self.throttle_value); th.addWidget(self.throttle_unit)
        build_grid.addWidget(self.throttle_frame, 4, 0, 1, 3)
        card_layout.addLayout(build_grid)

        # ---------- RUN ----------
        lbl_run = QLabel("Run"); lbl_run.setProperty("role", "section")
        card_layout.addWidget(lbl_run); card_layout.addWidget(divider())

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

        # Actions row
        actions_row = QHBoxLayout()
        self.clone_btn = QPushButton("Clone  Prepare"); self.clone_btn.setObjectName("primaryBtn"); self.clone_btn.clicked.connect(self.start_clone)
        actions_row.addWidget(self.clone_btn)

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
        run_grid.addLayout(actions_row, 3, 0, 1, 3)

        # URL tools
        url_tools = QHBoxLayout()
        self.copy_url_btn = QPushButton("Copy URL"); self.copy_url_btn.setObjectName("ghostBtn"); self.copy_url_btn.setEnabled(False); self.copy_url_btn.clicked.connect(self.copy_url)
        self.open_url_btn = QPushButton("Open in Browser"); self.open_url_btn.setObjectName("ghostBtn"); self.open_url_btn.setEnabled(False); self.open_url_btn.clicked.connect(self.open_in_browser)
        url_tools.addWidget(self.copy_url_btn); url_tools.addWidget(self.open_url_btn); url_tools.addStretch(1)
        run_grid.addLayout(url_tools, 4, 0, 1, 3)

        card_layout.addLayout(run_grid)

        # Console
        t = QLabel("Console Log:"); t.setProperty("role", "title")
        card_layout.addWidget(t)
        self.console = QTextEdit(); self.console.setReadOnly(True); self.console.setMinimumHeight(220); card_layout.addWidget(self.console)

        # Status bar
        self.status_label = QLabel("No container running"); self.status_label.setObjectName("status"); self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_shadow = QGraphicsDropShadowEffect(self.status_label); status_shadow.setBlurRadius(18); status_shadow.setOffset(0, 6); status_shadow.setColor(Qt.GlobalColor.black)
        self.status_label.setGraphicsEffect(status_shadow)
        card_layout.addWidget(self.status_label)

        # timers & init
        self.status_timer = QTimer(); self.status_timer.timeout.connect(self.check_container_status); self.status_timer.start(3000)
        self.set_advanced_mode(False)
        self._align_label_column()
        self.refresh_run_buttons()

    # ----- advanced toggle -----
    def set_advanced_mode(self, enabled: bool):
        self.size_frame.setVisible(enabled)
        self.throttle_frame.setVisible(enabled)

    # ----- helpers -----
    def _align_label_column(self):
        labels = [self.lbl_url, self.lbl_dest, self.lbl_img, self.lbl_bind_ip, self.lbl_port, self.lbl_cport]
        fm = QFontMetrics(labels[0].font())
        w = max(fm.horizontalAdvance(l.text()) for l in labels) + 8
        for l in labels:
            l.setFixedWidth(w)

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

    # ----- actions -----
    def start_clone(self):
        if self.container_id is not None:
            self.console.append("Stop the running container before creating a new one."); return

        url = self.url_input.text().strip()
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

        if port_in_use(self.current_host_ip, self.current_port):
            self.console.append(f"Port {self.current_port} appears in use on {self.current_host_ip}.")
            default = max(1, min(65535, self.current_port + 1))
            port, ok = QInputDialog.getInt(self, "Port in Use", "Enter a different port:", default, 1, 65535)
            if not ok: return
            self.current_port = port
            self.port_input.setValue(port)

        size_cap = None
        if self.adv_toggle.isChecked() and self.size_cap_checkbox.isChecked():
            mul = {"MB":1024**2,"GB":1024**3,"TB":1024**4}[self.size_cap_unit.currentText()]
            size_cap = self.size_cap_value.value() * mul
        throttle = None
        if self.adv_toggle.isChecked() and self.throttle_checkbox.isChecked():
            mul = 1024 if self.throttle_unit.currentText()=="KB/s" else 1024**2
            throttle = self.throttle_value.value() * mul

        if self.build_checkbox.isChecked() and not docker_name:
            self.console.append("Docker image name is required when building an image."); return

        self.console.clear()
        worker = CloneThread(
            url, project_dir_name, save_path,
            self.build_checkbox.isChecked(),
            host_port=self.current_port, size_cap=size_cap, throttle=throttle,
            host_ip=self.current_host_ip, container_port=self.current_container_port
        )
        self.clone_thread = worker
        worker.progress.connect(self.update_console)
        worker.finished.connect(self.clone_finished)
        worker.start()

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
                f.write(
                    "server {\n"
                    f"    listen {container_port};\n"
                    "    server_name localhost;\n"
                    "    root /usr/share/nginx/html;\n"
                    "    index index.html;\n"
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
             "-v",f"{folder}:/usr/share/nginx/html",
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

    def update_console(self, msg):
        self.console.append(msg); self.console.ensureCursorVisible()

    def clone_finished(self, log, docker_success):
        self.console.append("\nProcess finished.")
        self.refresh_run_buttons()
        self.update_status(False, cid=None)
        self.console.ensureCursorVisible()

# ---------- main ----------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    icon_path = find_icon("icon.png")
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))
    window = DockerClonerGUI()
    window.show()
    sys.exit(app.exec())
