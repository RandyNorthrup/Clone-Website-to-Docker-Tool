# Clone Website to Docker Tool

A desktop utility that clones any public website to a local folder using `wget`, then packages and serves it with Docker + Nginx. It supports one-click build/run, serving directly from a folder (no build), **custom bind IP**, **host/target port mapping**, and a modern dark UI.

---

## ✨ Features

- **Point-and-click cloning** with `wget --mirror` (link conversion, assets, no-parent).
- **Self-contained output** in the directory you select: Dockerfile, optional `nginx.conf`, and a README per project.
- **Build image** (optional). On success, inputs are cleaned so only the README remains in the project dir.
- **Two run modes**
  - **Run Created Container** (built image).
  - **Serve From Folder (no build)** via bind-mount + a minimal Nginx config.
- **Networking controls**
  - **Bind IP** (e.g., `127.0.0.1`, `0.0.0.0`, or your LAN IP).
  - **Host Port** (left side of `-p`).
  - **Container Port** (right side of `-p`).
- **Safety & ergonomics**
  - Detects “port in use” and offers an alternative.
  - Disables “Clone & Prepare” while a container launched by the app is running.
  - Live status pill with uptime, port mapping, and project path.
  - “Copy URL” & “Open in Browser” buttons.
- **Advanced options** (toggle)
  - Download size quota and rate throttling for `wget`.
- **Modern dark UI** with rounded corners/shadows, and a centered icon header (web ➜ arrow ➜ docker).

---

## 📦 Requirements

- **Python** 3.9+  
- **PySide6** (`pip install PySide6`)
- **wget** on PATH  
  - macOS: `brew install wget`  
  - Windows: https://eternallybored.org/misc/wget/ (add to PATH)  
  - Linux (Debian/Ubuntu): `sudo apt-get install -y wget`
- **Docker** (optional, required to build/run)
  - macOS: `brew install --cask docker`
  - Windows: `winget install Docker.DockerDesktop`
  - Linux: `sudo apt-get install -y docker.io` (or distro equivalent)

> The app will still **clone** without Docker installed. Run buttons are disabled until Docker is available.

---

## 🚀 Quick Start

1. **Install deps**
   ```bash
   pip install PySide6
   ```
   Ensure `wget` and Docker are installed (see above).

2. **Run the app**
   ```bash
   python path/to/cw2dt.py
   ```

3. **Prepare a project**
   - Enter **Website URL**.
   - Choose **Destination Folder**.
   - (Optional) check **Build Docker image after clone** and set **Docker Image Name**.
   - (Optional) open **Advanced Options** for quota/throttle.
   - In **Run** section, set **Bind IP**, **Host Port**, and **Container Port**.
   - Click **Clone  Prepare**.

4. **Serve it**
   - **Run Created Container** (uses the built image), or
   - **Serve From Folder (no build)** (bind-mounts your folder into `nginx:alpine`).
   - Use **Open in Browser** or **Copy URL**.

5. **Stop**
   - Click **Stop Container** to stop the container that was started from this GUI.

---

## 🧭 UI Tour

- **Source**: Website URL and Destination folder.  
- **Build**: Enable image build and set **Docker Image Name**. Toggle **Advanced Options** to limit mirror size or throttle rate.  
- **Run**:  
  - **Bind IP** (e.g., `127.0.0.1` for local only, `0.0.0.0` for all interfaces, or your LAN IP).  
  - **Host Port** (**external** port your browser uses).  
  - **Container Port** (**internal** Nginx port—reflected in the Dockerfile/`nginx.conf` for built images).  
  - **Run Created Container** uses `-p <bind_ip>:<host_port>:<container_port> <image>`.  
  - **Serve From Folder** creates a tiny Nginx conf that listens on your chosen **container port** and bind-mounts it along with the site folder.

- **Status bar**: Live 3-second refresh. Shows mode, mapping (`host_ip:host_port → container:container_port`), uptime, and project path.

- **Buttons auto-enable/disable** based on state (Docker availability, running container, prepared folder, local image presence).

---

## 🗂️ Output Layout (after “Clone  Prepare”)

```
<Destination>/<project_name>/
  Dockerfile                # EXPOSE <container_port>
  nginx.conf                # listen <container_port>
  <website content>         # mirrored files (removed after successful build)
  README_<project>.md       # per-project usage notes (always regenerated last)
  .folder.default.<port>.conf  # created on demand for "Serve From Folder"
```

> If the image **build succeeds**, the tool cleans up all inputs (site files, Dockerfile, nginx.conf) and leaves only the README (so the folder is just documentation). “Serve From Folder” requires a prepared folder; build cleanup means you’ll need to re-prepare if you want to run folder mode again.

---

## 🔧 How It Works (high level)

1. **CloneThread (QThread)** runs `wget` mirroring with optional `--quota` and `--limit-rate`.  
2. Detects **site root** (first folder containing an index file).  
3. Writes a **Dockerfile** and **nginx.conf** tuned to your **Container Port**.  
4. **Build** (optional). On success, cleans inputs and leaves README.  
5. **Run** uses `docker run` with `-p <bind_ip>:<host_port>:<container_port>`.  
   - **Folder mode** mounts the folder and a one-file Nginx config to listen on your chosen **Container Port**.

---

## 🔒 Legal & Ethics

- The tool sets `-e robots=off` and `--mirror`. **Only clone content you have the right to copy** and **respect site Terms of Service**, copyright, and robots policies when applicable.  
- Avoid cloning authenticated, rate-limited, or copyrighted resources without permission.  
- You are responsible for how you use this tool.

---

## 🧪 Common Workflows

### Build & run a local, portable image
1. Enter URL, dest folder, check **Build Docker image after clone**, set an image name.
2. Clone & build.
3. Click **Run Created Container**.

### Quick local preview (no build)
1. Clone (build unchecked).
2. Click **Serve From Folder (no build)**.  
3. Stop when finished.

### Expose to LAN
- Set **Bind IP** to your machine’s LAN IP (click **Detect LAN IP**).  
- Choose **Host Port** that’s open on your firewall/router.  
- Anyone on your LAN can visit `http://<LAN_IP>:<Host Port>`.

---

## 🆘 Troubleshooting

- **Docker not found**  
  Buttons are disabled. Install Docker (see Requirements) and reopen the app.

- **Permission denied (Linux)**  
  Add your user to the `docker` group and re-login:
  ```bash
  sudo usermod -aG docker $USER
  ```

- **Port already in use**  
  The app will prompt for another port. You can also change **Bind IP** to isolate to localhost.

- **Cloning fails or is partial**  
  Some sites rely on dynamic backends; a static mirror may not work fully. Consider a different mirroring strategy if needed.

- **Slow or huge downloads**  
  Use **Advanced Options**: set a size quota and/or throttle rate.

- **“Open in Browser” does nothing**  
  Ensure a container is running and no firewall blocks the chosen **Host Port**. If **Bind IP** is `0.0.0.0`, the app uses `localhost` for the URL.

- **Icons not visible**  
  Place `web_logo.png`, `arrow_right.png`, and `docker_logo.png` in `./images/` (next to the script). The app also searches the script dir and current working dir.

---

## 🛠️ Building a Standalone App (optional)

Use PyInstaller:

```bash
pip install pyinstaller
pyinstaller -y --noconfirm --windowed --name "Clone Website to Docker Tool" cw2dt.py
```

- Add `--icon path/to/your_app_icon.ico/icns` if you’ve created one.
- Bundle `images/` alongside the executable.

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

---

## 📄 License

Add your preferred license (e.g., MIT) here.

---

## 🗺️ Roadmap (ideas)

- Optional auth for private sites (cookies/session export).  
- Parallel fetch or alternate crawlers.  
- Built-in bandwidth monitor and detailed progress.  
- Light theme toggle.

---

### Credits

- **Nginx** (Alpine), **Docker**, **wget**, **PySide6**.  
- App icon imagery: web → arrow → docker (place in `images/`).

