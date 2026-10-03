# Setup Readiness

Read-only audit of the development tools required by plan §12 Step 2. **Nothing was installed or reconfigured during this audit.** No environment variables, token files, or env files were printed.

**Audited:** 2026-10-02, in the Claude Code session shell (PowerShell 5.1)
**Machine:** Windows 11 Home, build 26200 · 31.1 GB RAM · firmware virtualization enabled · hypervisor not running · session not elevated (standard user)

## Summary

| Tool | Installed version | Status | Missing dependency / issue |
|---|---|---|---|
| Git | 2.54.0.windows.1 | ✅ Ready | — |
| GitHub CLI | 2.102.0 | ✅ Ready (auth OK) | Not on PATH in the current session; open a fresh terminal |
| Python | **3.12.10** (default `python`), also 3.11.1 | ✅ Ready (updated 2026-10-02) | 3.8.8 uninstalled. The project still pins its own version in Prompt 10. |
| uv | **0.12.22** | ✅ Ready (installed 2026-10-02) | — |
| Docker CLI | **29.8.1** (Docker Desktop 4.93.0, per-user) | ✅ Installed 2026-10-02 | Fresh terminal needed for PATH |
| Docker engine | **29.8.1** (linux/amd64, WSL 2 kernel 6.18.40.1) | ✅ Verified 2026-10-02 | — |
| Claude Code | 2.1.288 | ✅ Ready | `claude doctor` not run (interactive). Human check below. |

## Details per tool

### Git: ready
- **Found:** `C:\Program Files\Git\cmd\git.exe`, version 2.54.0.windows.1
- **Identity:** `user.name` configured (the commit on `main` used it)
- **Install source:** https://git-scm.com/download/win
- **Verify:** `git --version`

### GitHub CLI: ready
- **Found:** `C:\Program Files\GitHub CLI\gh.exe`, version 2.102.0 (installed 2026-10-02 with `winget install --id GitHub.cli -e`)
- **Auth (nonsecret status):** logged in to github.com as `tonykjin` through the keyring. Protocol https. Scopes: gist, read:org, repo, workflow.
- **Issue:** the install directory is on the machine PATH, but this session's shell was started before the install. A fresh terminal fixes it. No action needed.
- **Install source:** https://cli.github.com/ · https://github.com/cli/cli#windows
- **Verify:** `gh --version` then `gh auth status`

### Python: ready (changed after the audit, 2026-10-02, at the user's request)
- Python 3.8.8 uninstalled with its own quiet uninstaller (exit 0); the user confirmed no projects depend on it.
- Python 3.12 updated from 3.12.3 to **3.12.10** (`winget upgrade --id Python.Python.3.12 -e`).
- User PATH: removed the `Python38` entries, added `Python312\Scripts\` and `Python312\` ahead of `Python311`. The previous PATH value was backed up first.
- Verified in a refreshed shell: `python` = 3.12.10 and `pip` = 25.0.1, both from `Python312`. `py -0p` lists 3.12 (default) and 3.11.
- **Leftover:** `C:\Users\tonyj\AppData\Local\Programs\Python\Python38` still holds orphaned pip packages (pdf/docx/openpyxl/opencv/numpy). Nothing points to it anymore. A safety hook blocked Claude from deleting it, so delete it by hand.

#### Original audit finding (superseded)
- **Found by `py -0p`:** 3.12.3 (launcher default), 3.11, 3.8. `python` on PATH resolves first to `Python38\python.exe` (3.8.8). The Windows Store `python`/`python3` aliases also exist.
- **Risk:** 3.8 is past end-of-life and too old for current FastAPI/Pydantic/Streamlit releases. A tool that runs a bare `python` would pick it up.
- **Recommendation (no install needed):** let uv manage the interpreter. Prompt 10 should pin the project's Python version (for example `.python-version` plus `requires-python` in `pyproject.toml`) and choose a supported version after checking dependency compatibility. **Don't** change the global PATH order or uninstall 3.8. Other projects may depend on it.
- **Install source (if ever needed):** https://www.python.org/downloads/windows/ · or `uv python install <version>`
- **Verify:** `py -0p` · `uv run python --version` (inside the project, after uv is installed)

### uv: ready
- Installed 2026-10-02: `winget install --id=astral-sh.uv -e` gave **uv 0.12.22**. It's on the user PATH in a fresh terminal.

#### Original audit finding (superseded)
- **Official docs:** https://docs.astral.sh/uv/getting-started/installation/ (fetched 2026-10-02)
- **Official Windows options, none needing admin:**
  - Standalone installer: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`. Installs to `~\.local\bin`, which is already on PATH (Claude Code lives there).
  - WinGet: `winget install --id=astral-sh.uv -e`
- **Recommendation:** WinGet, to match how `gh` was installed. Claude can run it in Prompt 03.
- **Verify:** `uv --version` (in a fresh terminal)

### Docker: ready (verified 2026-10-02, Prompt 03)
- **Engine verified after the BIOS fix (boot 19:49):** `HypervisorPresent=True`. The hypervisor log shows a normal start (events 2, 129, 156, 165) and no new event 44. The BIOS is still 2.02.AS01: you changed the setting, no update was needed.
  - `docker version`: Client 29.8.1 / **Server 29.8.1**, linux/amd64
  - `docker info`: Docker Desktop, kernel 6.18.40.1-microsoft-standard-WSL2, 16 CPUs, about 15.2 GiB memory
  - `docker context show`: `desktop-linux`
  - `wsl -l -v`: `docker-desktop` Running, VERSION 2
  - `docker run --rm hello-world`: "Hello from Docker!", exit 0
  - `docker compose version`: v5.5.1
  - You launched Docker Desktop and accepted the subscription agreement.
- **WSL:** `wsl --version` shows WSL 3.0.1 and kernel 6.18.40.1-1. `wsl --status` shows default version 2. The `vmcompute` and `WSLService` services are running. You ran `wsl --install` and restarted (boot at 19:25). No Linux distro is installed (`wsl -l -v`), which Docker doesn't need.
- **Docker Desktop 4.93.0:** Claude downloaded the official installer (`desktop.docker.com/win/main/amd64`). Its Authenticode signature is Valid, signed by CN=Docker Inc. Claude ran `install --user --quiet --backend=wsl-2` and it exited with code 0. Claude did **not** pass `--accept-license`.
- **CLI:** `C:\Users\tonyj\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe` gives `Docker version 29.8.1, build 4a63305`. It's on the user PATH, so a fresh terminal picks it up.
- **Engine (before the BIOS fix):** `docker version` fails with `failed to connect to the docker API at npipe:////./pipe/docker_engine`. The engine starts only after you launch Docker Desktop and accept the subscription agreement.

- **First launch failed (2026-10-02):** Docker Desktop shows "Virtualization support not detected". Diagnosis (read-only):
  - The Windows hypervisor isn't running (`HypervisorPresent=False`). The **System event log shows Hyper-V-Hypervisor event 44 at both boots (19:24 and 19:25): "Hypervisor launch failed; Either No Execute feature (NX) not present or not enabled in BIOS."**
  - Windows features are fine: VirtualMachinePlatform and WSL are enabled, and the hypervisor tried to launch.
  - CPU support is fine: AMD Ryzen 7 7800X3D has firmware virtualization (SVM), SLAT and VM monitor extensions. Windows reports DEP as available with policy OptIn (2), so DEP isn't turned off in Windows.
  - Firmware: ASRock B650I Lightning WiFi, AMI BIOS **2.02.AS01 (2023-11-16)**.
  - **Fix (human, in the BIOS):** enable the NX / no-execute setting if the BIOS has one, keep SVM enabled, save and reboot. If no NX option exists or it's already enabled, update the BIOS from ASRock's support page for this board, then check again. Claude doesn't change firmware or security settings.
  - **Verify after reboot:** `(Get-CimInstance Win32_ComputerSystem).HypervisorPresent` should be `True`, with no new event 44. Then launch Docker Desktop.

#### Original audit finding (superseded)
- **Found:** no `docker` command and no Docker Desktop install. WSL reports *"The Windows Subsystem for Linux is not installed."*
- **Why WSL is required:** Docker's Windows guide says Windows Home and Education editions run Linux containers only, through the **WSL 2 backend**. It requires WSL 2.1.5 or later, at least 8 GB RAM (we have 31.1 GB), a 64-bit CPU with SLAT, and virtualization enabled in BIOS/UEFI (it is: `VirtualizationFirmwareEnabled = True`). No BIOS change is needed.
- **Official docs:**
  - Docker Desktop for Windows: https://docs.docker.com/desktop/setup/install/windows-install/ (fetched 2026-10-02)
  - WSL install: https://learn.microsoft.com/en-us/windows/wsl/install (fetched 2026-10-02)
- **Step 1: install WSL. Needs administrator rights and a restart (human).**
  Microsoft documents `wsl --install` run from PowerShell **as Administrator**, followed by a restart. It enables Windows optional features (Virtual Machine Platform / WSL), which is an OS change. This session is not elevated, so Claude cannot and should not do it. By default it also installs Ubuntu. That isn't required for Docker but is harmless. Expect a prompt to create a Linux username and password the first time Ubuntu launches.
- **Step 2: install Docker Desktop.** No admin needed per-user, but the first launch is a GUI step.
  Per-user install (`"Docker Desktop Installer.exe" install --user`) needs no admin according to Docker's docs. Claude can download and run the installer in Prompt 03 after WSL is in place, or you can run the wizard. Choose the WSL 2 backend.
  On first launch, Docker Desktop shows its **subscription service agreement**, which a human must accept in the GUI.
- **Licensing (human decision):** Docker Desktop is free for personal use, education, and small businesses. A paid subscription is required for commercial use by organizations with **more than 250 employees or more than US$10 million in annual revenue**. Confirm Loam Labs' status. Claude won't accept the agreement for you.
- **Verify the engine, not just the CLI:**
  - `docker version` must show a **Server:** section. A CLI-only output with a connection error means the engine isn't running.
  - `docker info`
  - `docker run --rm hello-world`
  - `wsl -l -v` should list `docker-desktop` with VERSION 2

### Claude Code: ready
- **Found:** `C:\Users\tonyj\.local\bin\claude.exe`, version 2.1.288 (native installer location)
- **Not run:** `claude doctor` opens an interactive screen, so it isn't a non-interactive audit check. Run it yourself in a terminal.
- **Install source:** https://code.claude.com/docs/en/setup
- **Verify:** `claude --version` · `claude doctor`

## Who does what (Prompt 03)

| Action | Who | Why |
|---|---|---|
| ~~Install uv~~ | Done 2026-10-02 | — |
| ~~Upgrade Python / remove 3.8~~ | Done 2026-10-02 | — |
| Delete the leftover `Python38` folder | **You** | Claude's deletion was blocked by a safety hook |
| Pin the project Python version | **Claude**, in Prompt 10 (scaffold) | Project config, not a system change |
| ~~`wsl --install` (Administrator)~~ | Done by you | — |
| ~~Restart Windows~~ | Done by you (boot 2026-10-02 19:25) | — |
| ~~Install Docker Desktop (per-user, WSL 2 backend)~~ | Done by Claude 2026-10-02 | — |
| ~~Launch Docker Desktop and accept the subscription agreement~~ | Done by you | — |
| ~~Enable NX in the BIOS (hypervisor event 44)~~ | Done by you (boot 19:49) | — |
| Confirm Docker licensing tier | **You** | Business fact |
| Run `claude doctor` | **You** | Interactive screen |
| Open a fresh terminal | **You** | Picks up the new PATH entries for `gh` and uv |

## What doesn't need Docker yet

Docker is first needed for local Postgres (POC-02 Compose file, then POC-06 migrations). Prompts 03–09 and the first parts of POC-02 can go ahead while WSL and Docker are being set up.
