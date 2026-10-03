# Execution Status

Handoff record for Claude Code sessions. GitHub Issues stay the source of truth for engineering status once they exist (Prompt 09). No secrets or restricted provider payloads belong in this file.

**Last updated:** 2026-10-02
**Baseline:** `docs/project-plan.md` (Section 12), executed via `docs/claude-code-prompt-playbook.md`
**Repository:** https://github.com/tonykjin/food-vision-poc (private, default branch `main`)
**Local workspace:** `C:\Users\tonyj\OneDrive\Desktop\food-vision-poc`

## Current step

**Prompt 03: install missing prerequisites.** Prompt 03 **passed** (2026-10-02).

**Prompt 04: local repository and document skeleton.** Prompt 04 **complete**: commit `cb2b92c`, local only, not pushed.

**Prompt 05: CLAUDE.md and permission settings.** Status: **complete** (2026-10-02). Committed as `602a22a`. Re-checked in a fresh session started from the project root (2026-10-02). `/context` lists 2 memory files: `CLAUDE.md` and the imported `docs/project-plan.md`. Read of `.env.agent.local` and `secrets/x.json` was denied, and Read of `.env.example` succeeded (the secret files were confirmed absent before the test). No changes were needed.

**Prompt 06, push only (you asked to commit and push):** `main` was pushed to `origin` (`8339643..602a22a`). `gh repo view` shows PRIVATE, default branch `main`. The rest of Prompt 06 is still to do: branch protection, secret scanning, inviting collaborators.

## Completed steps

| Step | What happened | Evidence |
|---|---|---|
| Workspace setup (playbook §2) | Plan and playbook copied into `docs/` under the names the playbook specifies. | Commit `8339643` on `main` |
| Repo naming | Existing empty GitHub repo `fatsecret-PoC` renamed to `food-vision-poc`; local folder renamed to match; `origin` updated. | `gh repo view` returns `name: food-vision-poc`, `visibility: PRIVATE` |
| GitHub CLI (part of plan Step 2) | `gh` 2.102.0 installed with winget; authenticated as `tonykjin` (scopes: gist, read:org, repo, workflow). | `gh --version`, `gh auth status` |
| Prompt 01 | Created `docs/execution-status.md`, `docs/project-settings.md`, `docs/decisions/`. | This file |
| Prompt 02 | Read-only tool audit; created `docs/setup-readiness.md`. Nothing installed or reconfigured. | See Prompt 02 evidence below |
| Prompt 03, part 1 (user request) | Installed uv 0.12.22. Uninstalled Python 3.8.8 and updated 3.12 to 3.12.10, now the default `python` (user PATH updated). | Refreshed shell: `python --version` returns 3.12.10, `uv --version` returns 0.12.22 |
| Prompt 03, part 2 | You installed WSL and restarted. Claude installed Docker Desktop 4.93.0 per-user with the WSL 2 backend and without accepting the license. | `wsl --version` returns 3.0.1. Installer signature is Valid (Docker Inc) and it exited 0. `docker --version` returns 29.8.1. `docker version` cannot reach the engine yet. |
| Prompt 03 re-run (same session) | Nothing installed: every tool already present. Re-checked paths. | All 6 executables resolve (git, gh, python, uv, docker, claude). Docker Desktop process isn't running, `docker version` still can't reach the engine, and `wsl -l -v` shows no `docker-desktop` distro yet. |
| Prompt 03, part 3 | You enabled NX in the BIOS (hypervisor event 44 fixed), launched Docker Desktop and accepted its agreement. Claude verified the engine. | `HypervisorPresent=True`. Docker server 29.8.1 (linux/amd64). `wsl -l -v` shows `docker-desktop` v2 Running. `hello-world` exited 0. Compose v5.5.1. |
| Prompt 04 | Repo already existed at the project root, so no `git init` and no parent repo. Added `README.md`, `.gitignore`, `.env.example` (empty values, plan §6 names) and committed the Prompt 01–04 docs. No remote changes, no push. | `git check-ignore`: `.env`, `.env.*.local`, `secrets/`, images, `/data/`, `/work/`, logs, `/reports/` and `.venv/` are ignored. `.env.example`, docs, `migrations/`, `pyproject.toml`, `uv.lock` and `src/foodvision/data/` stay trackable. The staged list was checked for credentials and images. |
| Prompt 05 | Created `CLAUDE.md` (about 50 lines, links to the plan), `.claude/settings.json` (Read and Edit deny rules anchored at the project root for env, secrets and key files; `disableBypassPermissionsMode`) and `docs/credential-handling.md` (boolean-only presence checks, known limits). Rule syntax was checked against https://code.claude.com/docs/en/permissions. | Live test: Read of `.env.agent.local` and `secrets/x.json` was denied. Bash `touch` of protected names was denied. Read of `.env.example` succeeded. |

## Pass/fail evidence: Prompt 02

| Tool | Result | Evidence (2026-10-02) |
|---|---|---|
| Git | Pass | `git --version` returns 2.54.0.windows.1 |
| GitHub CLI | Pass | `gh --version` returns 2.102.0. `gh auth status`: logged in as `tonykjin`. Not on this session's PATH until a fresh terminal. |
| Python | Pass with risk | `py -0p` lists 3.12.3 (default), 3.11, 3.8. A bare `python` runs 3.8.8 (end-of-life). Pin the version in Prompt 10. |
| uv | **Fail: missing** | `uv` not found |
| Docker CLI | **Fail: missing** | `docker` not found; Docker Desktop not installed |
| Docker engine | **Fail: not running** | WSL not installed (`wsl --status`). Virtualization is enabled in firmware. |
| Claude Code | Pass | `claude --version` returns 2.1.288. `claude doctor` not run (interactive), so it's a human check. |

Audit caveat: this Prompt 02 run happened in the session started from `C:\Users\tonyj`, not from the project root. The tool results don't depend on the working directory.

## Pass/fail evidence: Prompt 01

| Gate | Result | Evidence |
|---|---|---|
| Working directory and Git boundary inspected | Pass | `git rev-parse --show-toplevel` returns `C:/Users/tonyj/OneDrive/Desktop/food-vision-poc`. There is no `.git` in `OneDrive\Desktop` or `OneDrive`, so no parent repository is involved. `C:\Users\tonyj` is not a Git repo. |
| Confirmed dedicated workspace | Pass, with one caveat | The repo contains only this project's `docs/`. **Caveat:** this Claude session was started in `C:\Users\tonyj`, not the project root. Work used absolute paths inside the project only. Restart `claude` inside the project directory before Prompt 02. |
| A/B scope stated accurately | Pass | Summary given in the session report. Matches plan §1, §8–10. |
| Nonsecret progress/config record created | Pass | `docs/execution-status.md`, `docs/project-settings.md` |
| No accounts, publishing, paid APIs, or app code | Pass | No files were created outside `docs/`. Nothing in this prompt was committed or pushed. |

## Deviations from the playbook order

- The private GitHub repo and its first commit (docs only) were created **before** Prompts 04 and 06. When those prompts run, they should **reconcile with the existing repo and remote**: no `git init`, no new repo, no second remote. See `docs/decisions/0001-adopt-plan-baseline.md`.
- The first commit contains only the two source docs. Prompt 04 added `README.md`, `.gitignore` and `.env.example` in a local commit. `CLAUDE.md` comes in Prompt 05.

**Prompt 07: provider-access checklist.** Status: **complete** (2026-10-02). Commit `79217aa`, pushed to `origin/main`.
- Fetched the official fatsecret (image v2, OAuth, editions, terms), USDA (API guide, downloads, key signup) and Anthropic (vision, structured outputs, models, API overview) docs on 2026-10-02.
- Created `docs/provider-readiness.md` and `docs/vendor-questions-fatsecret.md`. The draft was **not sent**.
- Findings:
  - fatsecret Terms §1.5 requires removing non-storable content within 24 hours.
  - fatsecret token requests need registered IPs.
  - Basic and Premier Free cover US data only and require attribution.
  - Whether the image add-on needs Premier is unclear (sources conflict).
  - The repo sits under OneDrive, which is a secret-sync risk.
- No accounts were created, no messages sent, no keys handled.

**Prompt 08: record nonsecret answers and permissions.** Status: **complete** (2026-10-02). Commit `79217aa`, pushed to `origin/main`.
- Final boolean check (user ran `scripts/check-env-presence.sh`): all five variables are set, `ANTHROPIC_API_KEY` is in the agent file only, and it's not set in the shell.
- API billing is prepaid Console credits with auto-reload (user-reported).
- No live call has been made, so validity is unverified until Prompt 19.
- No user edits to the settings files were found. The facts given in chat are recorded: Claude Code uses the Max plan, App B uses pay-as-you-go Console credits in the default workspace, and the user reports a key was created.
- Added a permission-decisions log: fatsecret has **no written decision**, so persistence stays off. Also added a credential-presence table and the proceed/blocked task list to `docs/provider-readiness.md`.
- **Credential presence is not verified:** Claude's sandbox blocks the file. The user needs to run the `!` boolean check.
- **User decisions (2026-10-02):** all role owners are Tony Jin (`tonykjin`), the pilot region is US, there's no dollar budget cap (per-scan call limits and the live opt-in still apply), and the repo stays under OneDrive (risk accepted).
- **Credential presence (user-run boolean check, 2026-10-02):** `FATSECRET_CLIENT_ID`, `FATSECRET_CLIENT_SECRET` and `USDA_API_KEY` are set. `ANTHROPIC_API_KEY` is **missing** from `.env.agent.local`; the user is re-saving it. Presence isn't validity, and fatsecret add-on access and rights stay unconfirmed.
- **Still PENDING (non-blocking):** GitHub owner long-term confirmation and cofounder invites. No paid calls were made.

**Prompt 09: GitHub backlog.** Status: **complete and merged** (2026-10-02). Commit `bf7c69b` went in via [PR #17](https://github.com/tonykjin/food-vision-poc/pull/17), merge commit `3255da5`. No CI checks existed yet. The merge was authorized by the sole reviewer `tonykjin` in the session.
- The repo had no issues, project labels or milestones beforehand, so nothing was duplicated.
- Created 9 labels, the 4 plan §15 milestones and issues #1–#16, all assigned to `tonykjin`. The real numbers were confirmed from the returned URLs and match the POC IDs. Dependencies link to the real issue numbers.
- Added `docs/github-issue-map.md`, `docs/verification-matrix.md`, `.github/ISSUE_TEMPLATE/task.md` and `config.yml`, and `.github/pull_request_template.md`.
- Blocked or partial: #1 (vendor/partial), #8 (live), #12 (real meals), #15 (data). No issue was closed.

**Prompt 10: POC-02 scaffold and CI** ([#2](https://github.com/tonykjin/food-vision-poc/issues/2)). Status: **merged** (2026-10-02) via [PR #18](https://github.com/tonykjin/food-vision-poc/pull/18), merge commit `254d1f6`.
- CI run 37094966374 passed: frozen install, Ruff, and 28 tests on ubuntu-latest.
- The first CI run failed at setup because `setup-uv@v10` has no floating tag. Fixed by pinning `v10.2.0`.
- Issue #2 stays **open** until the user does the README human UI checks. Evidence is commented on #2.
- **Built:**
  - uv project (Python 3.12, `uv.lock`; key versions: fastapi 0.142.2, streamlit 1.65.0, pydantic 2.13.5, sqlalchemy 2.1.3, alembic 1.20.0, httpx 0.28.1)
  - per-app settings that read only their own env file
  - placeholder result/error contracts (replaced in POC-03)
  - MOCK pipeline (null nutrients, labeled)
  - API factory plus `provider_app`/`agent_app` (`/health`, `/v1/analyze`)
  - `foodvision doctor`
  - shared Streamlit page plus `apps/provider_ui.py`/`agent_ui.py`
  - `infra/compose.yml` (postgres:17)
  - `.github/workflows/ci.yml`
  - README launch instructions
- **Verified:** `uv run ruff check .` passed. `uv run pytest`: 28 passed. `uv lock --check` and `uv sync --frozen` OK.
- **Live servers:** both mock APIs ran separately (8001/8002): health 200, mock analyze 200 with `is_mock` and null nutrients, empty upload 400 `invalid_image`, no file 422. `MOCK_MODE=false` gave 501 `not_implemented`. Both UIs served (`/_stcore/health` ok).
- **Other checks:** Compose Postgres 17.11 came up and was torn down. `doctor` on the real env files: A required set; B `ANTHROPIC_API_KEY` set, `VISION_MODEL` missing; isolation ok.
- **Not verified:** browser click-through of the upload flow (human checks in README) and the GitHub Actions run.

**Prompt 11: POC-03 contracts and nutrition arithmetic** ([#3](https://github.com/tonykjin/food-vision-poc/issues/3)). Status: **merged and closed** (2026-10-02) via [PR #19](https://github.com/tonykjin/food-vision-poc/pull/19), merge commit `076b696`. CI run 37095462061 passed: 97 tests.
- **Contracts:**
  - Schema 1.0 results: states, totals status, portion methods, food sources, confidence type with calibration-gated probability, and cross-field rules (partial can't claim complete totals; MOCK never complete; failed needs an error).
  - Request `AnalysisContext` (known weight only in the diagnostic mode).
  - Full plan §7 error codes.
- **Arithmetic:**
  - `nutrition/units.py` (4.184 kJ/kcal; ml↔g only with a density) and `nutrition/calculator.py` (per-100 g, per-100 ml and per-serving bases; nulls preserved; unresolved items excluded, not zero).
  - `nutrition/display.py` handles display-only rounding.
- **Selection:** `matching/selection.py` rejects IDs that aren't among the candidates (exact match).
- **APIs:** both build an `AnalysisContext` (SHA-256 of the upload) and return the shared models.
- **Verified:**
  - `ruff check` passed; `pytest`: 97 passed.
  - Mutation spot-check: unknown→0, ignored serving basis, and unresolved→complete were each caught by a test.
  - Both live mock APIs return schema-1.0 results that validate.

**Prompt 12: POC-04 shared image preparation** ([#4](https://github.com/tonykjin/food-vision-poc/issues/4)). Status: **implemented and verified locally** (2026-10-02) on branch `feat/poc-04-image-prep`. Not committed.
- **`imaging/prepare.py`:**
  - Validation: decodes by content (JPEG/PNG/WebP only); byte limit; pixel limit checked from the header before decoding; corrupt input gives a typed error.
  - Output: EXIF orientation applied; alpha flattened; resized to the longest-edge limit with aspect ratio kept and no crop or upscale; re-encoded from raw pixels so no EXIF/GPS/ICC survives.
  - Records original and processed SHA-256.
- **`imaging/profiles.py`:** a versioned `baseline` (512 px) profile. The `b_hires_1024` experiment is a separate named profile, and its `transform_version` includes a settings hash and the Pillow version.
- **`providers/fatsecret_limits.py`:**
  - Measures the exact serialized JSON body.
  - Limits re-checked 2026-10-02: `image_b64` ≤ 999,982 chars; whole body ≤ "1MB characters (1.048M)"; file ≤ 1.09 MB. A 90% safety margin applies.
  - Oversize is rejected before any send.
- **APIs:** both run uploads through the baseline profile (bad images get 400/413 even in live mode) and return `input` provenance. The schema stays 1.0 (additive optional field, no consumers yet).
- **Verified:**
  - `ruff check` passed; `pytest`: 127 passed.
  - Mutation spot-check: no EXIF rotation, no margin, and upscaling were each caught.
  - Live: the same 2000×1500 synthetic photo through both APIs gave an identical processed hash (512×384, same `prep-v1:baseline` version). Text uploaded as `.jpg` gave 400 `invalid_image`.
- **Environment notes:**
  - OneDrive locked `.venv` package metadata during `uv add`; used `uv add --no-sync`, then `uv sync` on retry.
  - A Python edit wrote one file as cp1252; it was converted back to UTF-8 and checked with `iconv` across all files.

## Blockers

- ~~Docker engine~~: resolved 2026-10-02. Local Postgres (POC-02, POC-06) is no longer blocked.

Known future blockers, recorded in `docs/project-settings.md`:

- Role owners and reviewers are PENDING. Prompt 09 assignments need them.
- fatsecret image add-on access and storage rights are PENDING. They block POC-01/08 live work only.
- Runtime model and test budget are PENDING. They block Prompt 19 and paid runs.

## Next task

User: run the README human UI checks for #2, then close it. Claude: **Prompt 12: POC-04 shared image preparation** ([#4](https://github.com/tonykjin/food-vision-poc/issues/4)). POC-05 (#5) and POC-06 (#6) are also unblocked by #3.

**Also still open: finish Prompt 06.** `main` is already pushed to the private `origin` (`tonykjin/food-vision-poc`). Still to do: branch protection on `main` and secret scanning/push protection (as far as the GitHub plan allows), plus collaborator invites. Each of these changes the GitHub account, so confirm with the user before applying it.

## Issues / PRs

16 issues (#1–#16), 4 milestones and 9 project labels were created 2026-10-02. The map is in `docs/github-issue-map.md`. Open with an external blocker: #1 (partial), #8, #12, #15.
- PR #17 (backlog docs): merged.
- PR #18 (POC-02): merged; #2 is open pending human UI checks.
