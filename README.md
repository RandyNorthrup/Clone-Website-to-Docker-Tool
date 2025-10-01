# Clone Website to Docker Tool

A desktop and CLI utility to clone any public or private website to a local folder using **wget2** (parallel, resumable, authenticated), then package and serve it with Docker + Nginx. Features a modern dark UI, advanced options, and full automation support.

---

## Features

- **Point-and-click cloning** (GUI) and full-featured CLI (`--headless`)
- **wget2** for fast, parallel, resumable downloads
- **Authenticated cloning**:
  - HTTP username/password
  - Browser cookie import (via `browser_cookie3`)
- **Advanced options**:
  - Download quota (size cap)
  - Bandwidth throttling
  - Parallel jobs (configurable)
  - JavaScript disabling (strip scripts, enforce CSP)
  - Pre-clone estimation (spider mode)
- **Self-contained output**:
  - Dockerfile, nginx.conf, README, imported_cookies.txt
- **Docker integration**:
  - Build Docker image after clone
  - Serve from folder (no build) using bind-mount and minimal nginx config
  - Custom bind IP, host port, container port
  - Live status bar (uptime, port mapping, project path)
  - One-click run/stop, open in browser, copy URL
- **Resume failed/partial clones**
- **Cross-platform**: macOS, Linux, Windows (with PowerShell support)
- **Dependency management**: auto-detects missing wget2, Docker, browser_cookie3, and provides install commands
- **Modern dark UI**: responsive, scalable, with icon header
- **Recent URLs**: remembers last 10 URLs for quick access

---

## Requirements

- **Python** 3.9+
- **PySide6** (`pip install PySide6`) for GUI
- **wget2** (not wget) on PATH
- **Docker** (for build/run/serve)
- **browser_cookie3** (`pip install browser_cookie3`) for cookie import (optional, but recommended for private/authenticated sites)
- **nginx** is not required on your host; the tool uses the official `nginx:alpine` Docker image

---

## Usage

### GUI

- Enter website URL and destination folder
- (Optional) Enable build, set Docker image name
- (Optional) Advanced: quota, throttle, parallel jobs, JS disable, cookie import
- Set bind IP, host port, container port
- Click **Clone  Prepare**
- Serve via **Run Created Container** or **Serve From Folder (no build)**
- Stop container, open in browser, copy URL

### CLI

- All features available via `--headless` mode
- Example:
  ```bash
  python cw2dt.py --headless --url "https://example.com" --dest "/path/to/output" --docker-name "site" --build --jobs 8 --auth-user "user" --auth-pass "pass" --estimate --serve-folder --bind-ip 0.0.0.0 --host-port 8080 --container-port 80
  ```

---

## Output Layout

```
<Destination>/<project_name>/
  Dockerfile
  nginx.conf
  <website content>
  README_<project>.md
  imported_cookies.txt
  .folder.default.<port>.conf
```

---

## Troubleshooting

- **Missing dependencies**: Use the GUI's "Fix Dependencies…" button for install commands
- **Permission denied (Linux)**: Add your user to the `docker` group and re-login
- **Port in use**: App prompts for another port
- **Cloning fails/partial**: Resume supported; check authentication/cookies
- **Icons not visible**: Place `web_logo.png`, `arrow_right.png`, `docker_logo.png` in `./images/` or script dir

---

## Roadmap

- Built-in bandwidth monitor and progress visualization
- Additional authentication methods (OAuth, SSO, etc.)
- More advanced error handling and reporting
- Enhanced site compatibility (dynamic sites, SPA support)

---

## Credits

- **Nginx** (Alpine), **Docker**, **wget2**, **PySide6**, **browser_cookie3**

---

## Author

Randy Northrup
