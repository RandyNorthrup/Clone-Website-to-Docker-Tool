# Clone Website to Docker Tool

A desktop utility to clone any public website to a local folder using **wget2** (parallel, resumable), then package and serve it with Docker + Nginx. Supports one-click build/run, folder serving (no build), custom bind IP, port mapping, cookie import, and a modern dark UI. Also includes a full-featured headless CLI for automation.

---

## ✨ Features

- **Point-and-click cloning** with `wget2 --mirror` (parallel, resumable, link conversion, assets, no-parent)
- **Self-contained output**: Dockerfile, nginx.conf, README per project
- **Build Docker image** (optional) and clean up inputs after success
- **Serve From Folder (no build)**: bind-mount + minimal Nginx config
- **Networking controls**: Bind IP, Host Port, Container Port
- **Cookie import**: Scan browser cookies for authenticated downloads
- **Advanced options**: Download quota, rate throttling, parallel jobs, JS disabling
- **Headless CLI**: Full-featured command-line mode for automation
- **Live status**: Uptime, port mapping, project path, auto-refresh
- **Safety**: Detects port in use, disables actions while running, auto-enables buttons
- **Modern dark UI**: Rounded corners, icon header, responsive layout

---

## 📦 Requirements

- **Python** 3.9+
- **PySide6** (`pip install PySide6`) for GUI
- **wget2** (not wget) on PATH
  - macOS: `brew install wget2`
  - Linux: `sudo apt-get install -y wget2` (Debian/Ubuntu) or use your distro's package manager
  - Windows: Use MSYS2 (`pacman -S mingw-w64-ucrt-x86_64-wget2`) or build from source
- **Docker** (optional, required to build/run)
  - macOS: `brew install --cask docker`
  - Windows: `winget install Docker.DockerDesktop`
  - Linux: `sudo apt-get install -y docker.io` (or distro equivalent)
- **browser_cookie3** (`pip install browser_cookie3`) for cookie import (optional, CLI and GUI)

> The app will still **clone** without Docker installed. Run buttons are disabled until Docker is available.

---

## 🚀 Quick Start

1. **Install dependencies**
   ```bash
   pip install PySide6 browser_cookie3
   # Install wget2 and Docker as above
   ```
2. **Run the app**
   ```bash
   python cw2dt.py
   ```
3. **Prepare a project**
   - Enter Website URL
   - Choose Destination Folder
   - (Optional) Build Docker image and set image name
   - (Optional) Advanced: quota, throttle, parallel jobs, JS disable, cookie import
   - Set Bind IP, Host Port, Container Port
   - Click **Clone  Prepare**
4. **Serve**
   - **Run Created Container** (built image)
   - **Serve From Folder (no build)** (bind-mounts folder into nginx:alpine)
   - Use **Open in Browser** or **Copy URL**
5. **Stop**
   - Click **Stop Container**

---

## 🧭 UI & CLI Tour

- **Source**: Website URL, Destination folder
- **Build**: Enable image build, set Docker image name, quota/throttle, parallel jobs, JS disable
- **Run**: Bind IP, Host Port, Container Port
- **Cookie Import**: Scan browser cookies for authenticated downloads
- **Status bar**: Live refresh, mode, mapping, uptime, project path
- **Buttons**: Auto-enable/disable based on state
- **CLI**: All features available via `--headless` mode (see below)

---

## 🗂️ Output Layout

```
<Destination>/<project_name>/
  Dockerfile                # EXPOSE <container_port>
  nginx.conf                # listen <container_port>
  <website content>         # mirrored files (removed after successful build)
  README_<project>.md       # per-project usage notes (always regenerated last)
  imported_cookies.txt      # if cookies imported
  .folder.default.<port>.conf  # for "Serve From Folder"
```

> After a successful build, the tool cleans up inputs and leaves only the README. To serve from folder again, re-prepare the project.

---

## 🔧 How It Works

1. Clone with `wget2` (parallel, resumable, quota/throttle, cookies, JS disable)
2. Detect site root (first folder with index file)
3. Write Dockerfile and nginx.conf for chosen container port
4. Build Docker image (optional)
5. Run container: `docker run -p <bind_ip>:<host_port>:<container_port> <image>`
6. Serve from folder: bind-mount folder and config into nginx:alpine

---

## 🔒 Legal & Ethics

- The tool sets `-e robots=off` and `--mirror`. **Only clone content you have the right to copy** and **respect site Terms of Service**, copyright, and robots.txt when applicable.
- Avoid cloning authenticated, rate-limited, or copyrighted resources without permission.
- You are responsible for how you use this tool.

---

## 🧪 Common Workflows

### Build & run a portable image
1. Enter URL, destination folder, enable build, set image name
2. Clone & build
3. Run Created Container

### Quick local preview (no build)
1. Clone (build unchecked)
2. Serve From Folder (no build)
3. Stop when finished

### Authenticated clone
- Scan browser cookies, enable "Use imported cookies"
- Clone site with authentication

### Expose to LAN
- Set Bind IP to your LAN IP (Detect LAN IP)
- Choose Host Port open on your firewall/router
- LAN users visit `http://<LAN_IP>:<Host Port>`

---

## 🆘 Troubleshooting

- **wget2 not found**: Install via your OS package manager (see Requirements)
- **Docker not found**: Buttons disabled. Install Docker and reopen the app
- **Permission denied (Linux)**: Add your user to the `docker` group and re-login:
  ```bash
  sudo usermod -aG docker $USER
  ```
- **Port already in use**: App prompts for another port, or change Bind IP
- **Cloning fails/partial**: Some sites need dynamic backends; static mirror may not work fully
- **Slow/huge downloads**: Use Advanced Options (quota/throttle)
- **Open in Browser does nothing**: Ensure container is running, firewall allows Host Port
- **Icons not visible**: Place `web_logo.png`, `arrow_right.png`, `docker_logo.png` in `./images/` or script dir
- **Cookie import fails**: Ensure `browser_cookie3` is installed and browser profile is accessible

---

## 🛠️ Building a Standalone App (optional)

Use PyInstaller:
```bash
pip install pyinstaller
pyinstaller -y --noconfirm --windowed --name "Clone Website to Docker Tool" cw2dt.py
```
- Add `--icon path/to/icon.ico/icns` if you have one
- Bundle `images/` alongside the executable

---

## 🔁 Command Reference

- **Run created image**
  ```bash
  docker run -d -p <bind_ip>:<host_port>:<container_port> <image_tag>
  ```
- **Serve from folder (no build)**
  ```bash
  docker run -d -p <bind_ip>:<host_port>:<container_port> \
    -v "<abs_project_dir>":/usr/share/nginx/html \
    -v "<conf>.conf":/etc/nginx/conf.d/default.conf:ro \
    nginx:alpine
  ```
- **Windows PowerShell**: Use double quotes for paths and backticks for line continuation

---

## 📄 License

MIT License. See [LICENSE](LICENSE).

---

## 🗺️ Roadmap

- Optional auth for private sites (cookies/session export)
- Parallel fetch or alternate crawlers
- Built-in bandwidth monitor and progress
- Light theme toggle

---

### Credits

- **Nginx** (Alpine), **Docker**, **wget2**, **PySide6**, **browser_cookie3**

---

## 👤 Author

**Randy Northrup**
