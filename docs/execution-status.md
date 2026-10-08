# Execution Status

Handoff record for Claude Code sessions. GitHub Issues stay the source of truth for engineering status once they exist (Prompt 09). No secrets or restricted provider payloads belong in this file.

**Last updated:** 2026-10-06
**Baseline:** `docs/project-plan.md` (Section 12), executed via `docs/claude-code-prompt-playbook.md`
**Repository:** https://github.com/tonykjin/food-vision-poc (private, default branch `main`)
**Local workspace:** `C:\Users\tonyj\Desktop\food-vision-poc` (fresh clone, 2026-10-06; outside OneDrive). The old OneDrive copy still exists and holds the env files.

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

**Prompt 12: POC-04 shared image preparation** ([#4](https://github.com/tonykjin/food-vision-poc/issues/4)). Status: **merged and closed** (2026-10-02) via [PR #20](https://github.com/tonykjin/food-vision-poc/pull/20). CI run 37096010263 passed: 127 tests.
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

**Prompt 13: POC-05 Measurement Kit** ([#5](https://github.com/tonykjin/food-vision-poc/issues/5)). Status: **merged and closed** (2026-10-02) via [PR #21](https://github.com/tonykjin/food-vision-poc/pull/21), merge commit `686e49e`. CI passed: 169 tests.
- **`measurement/` package (no Streamlit):**
  - `clock` (system plus manual test clock; monotonic ns and UTC)
  - `events` (payload-free Span/Attempt/Blocked/Scan records; UTC enforced; `client_total_ms` always None)
  - `spans.ScanRecorder` (parent spans, per-stage sums kept separate from wall time, budget authorization, one ScanRecord per scan)
  - `retry` (≤1 transient retry per logical request, Retry-After within the deadline, per-attempt timeout capped by remaining time, no stored provider text)
  - `budget`; `costs` (versioned PriceTable with no built-in prices; unknown stays unknown)
  - `storage_policy` (per-source/class/purpose; pending fatsecret keeps only payload-free metadata and IDs; no written grants recorded)
  - `sinks` (in memory)
- **Config:** `MAX_EXTERNAL_ATTEMPTS_PER_SCAN` and `MAX_SCAN_COST_USD` (optional, empty = no cap) are now common. App A is fixed at 0 model calls.
- **APIs:** both record every scan (failed uploads and 501 included) in `app.state.telemetry`; result metrics come from the ScanRecord.
- **Verified:**
  - `ruff check` passed; `pytest`: 169 passed.
  - Mutation spot-check: persisting restricted content, retrying auth, unknown cost counted as 0, and wall time summed from spans were each caught.
  - Live: both mock APIs returned recorder metrics.
- **Not done:** durable telemetry sink (POC-06), browser click-to-render timing (still "unavailable"), real price table (needs current pricing on the day a budget is set).

**Prompt 14: POC-06 database and private image storage** ([#6](https://github.com/tonykjin/food-vision-poc/issues/6)). Status: **merged and closed** (2026-10-02) via [PR #22](https://github.com/tonykjin/food-vision-poc/pull/22), merge commit `2c57506`. CI passed with the Postgres service: 191 tests, none skipped.
- **Schema:**
  - `data/models.py` covers the plan §5 tables in `food_catalog` / `telemetry` / `benchmark`, with FKs, unique and check constraints (basis consistency, non-negative or NULL nutrients, split and grade enums, calibration never on test), cascade/restrict/set-null deletion, indexes and an `is_synthetic` flag.
  - No bytea columns.
- **Migration:** Alembic migration `0001` creates the schemas, the NOLOGIN group roles `fv_inference` (no privileges at all on `benchmark`) and `fv_evaluator`, and the grants. PUBLIC is revoked. `MIGRATION_DATABASE_URL` is owner-only.
- **Code:**
  - `data/access.assert_inference_isolation` queries real privileges.
  - `data/object_store.py`: one file per image ID outside Git, consent and retention metadata, deletion with tombstone, `purge_expired`.
  - `data/repositories.py`: scan records, policy-filtered results, metric writes refused for pending fatsecret.
  - `doctor` now also flags `MIGRATION_DATABASE_URL` in app env files.
- **CI:** disposable `postgres:17` service with dummy credentials. `REQUIRE_DB_TESTS=true` makes DB tests fail rather than skip. Runs `alembic upgrade head`.
- **Verified locally** (disposable DBs on Compose Postgres 17):
  - `ruff check` passed. `pytest` with DB: 191 passed. Without DB: 173 passed, 18 skipped.
  - Empty → head → base → head round trip; migration matches models (`compare_metadata` empty).
  - A real `fv_inference` LOGIN user is denied `SELECT` on `benchmark.*` (InsufficientPrivilege), `SET ROLE fv_evaluator`, catalog inserts and image deletes.
  - Mutation: granting benchmark to inference fails 5 access tests.
  - `uv run alembic upgrade head` on the Compose DB is at `0001 (head)`.
- **Synthetic data:** all test rows are synthetic and flagged. They aren't evidence of recognition accuracy.

**Prompt 15: POC-07 USDA catalog import and retrieval** ([#7](https://github.com/tonykjin/food-vision-poc/issues/7)). Status: **merged and closed** (2026-10-02) via [PR #23](https://github.com/tonykjin/food-vision-poc/pull/23), merge commit `45fd7a6`. CI passed: 230 tests, none skipped. Details are in `docs/catalog.md`.
- **Subset** (`catalog/usda-subset-v1.json`): Foundation 2026-04-30 and SR Legacy 2018-04 JSON downloads (SHA-256 recorded), plus 4 documented Branded FDC IDs via the API. Core nutrients use a documented ID precedence.
- **Migration `0002`:** nutrient IDs, portion units, category, parsed preparation state, publication and retrieval metadata, generated tsvector with a GIN index.
- **Importer** (`foodvision import-usda`, `import-usda-api`, `catalog-report`):
  - Idempotent on re-runs.
  - Null entries skipped; negative values rejected, never clamped.
  - Portions only with a gram weight from the data; an ml branded serving gets no grams.
  - Real local import: 363 Foundation, 7,793 SR Legacy, 4 Branded (1 API request, 1 attempt). Re-runs replaced and inserted 0.
- **Tools** (`matching/retrieval.py`):
  - Full-text search with a preparation filter and separate branded and generic pools; ≤5 candidates; typed no-match.
  - Ranking keys: commodity-first, head noun, nutrient completeness.
- **Verified:**
  - `ruff check` passed. `pytest` with DB: 230 passed; without DB: 193 passed, 37 skipped.
  - Mutation spot-check: no prep filter, no relaxed threshold, branded mixed in, and negatives kept were each caught.
  - Gap report: 21 of 22 pilot probes matched; "chicken tikka masala" has no match.
- **Fixed along the way:**
  - A POC-05 test that was flaky ("412" could appear in random hex IDs).
  - The 0002 check constraint naming (`op.f`). The local dev DB constraint was renamed to match.
- **Known limits:** lexical top-1 isn't always the plainest record (olive oil, salmon). A correct generic record is in the top 5; POC-10 selection decides.

**Prompt 16: POC-08 fatsecret adapter and App A** ([#8](https://github.com/tonykjin/food-vision-poc/issues/8)). Status: **adapter merged** (2026-10-02) via [PR #24](https://github.com/tonykjin/food-vision-poc/pull/24), merge commit `efa8b26`. CI passed: 268 tests. **#8 stays open: live use is unverified.** Details are in `docs/app-a-fatsecret.md`.
- **`providers/fatsecret_client.py`:**
  - Token: reuse with a 5-minute margin, one refresh on code 13.
  - Errors: JSON-body codes mapped to typed errors; provider text dropped.
  - All attempts go through the Measurement Kit.
- **`pipelines/provider_native.py`:**
  - Eaten totals used as-is; per-serving scaled once only when totals are missing.
  - Missing/invalid values become unknown; ml portions unresolved.
  - 211 or no foods give `empty_recognition`.
- **Wiring:** App A live mode is ready when credentials are set (503 `authentication` otherwise). The fatsecret code is imported only by App A. UI attribution snippet added.
- **`foodvision smoke-fatsecret`:** opt-in (`ENABLE_LIVE_API_TESTS=true` plus `--confirm-one-request`), at most 1 token + 1 image request, payload-free output. **Not run.**
- **Verified:**
  - `ruff check` passed; `pytest` (no DB): 231 passed, 37 skipped.
  - Mutation spot-check: double-scaling, no token reuse, 211 raised, and negatives kept were each caught.
  - Real `provider_app` started live with real credentials and no model keys: `/health` ready, no agent/model modules loaded, no request made.
- **Live-unverified:** token issuance from this IP, scope/add-on access, real response fields, 211 behavior, latency and quotas. The written rights answers are still pending, and the vendor draft is unsent.

**Live smoke opt-in (2026-10-02):** the user authorized live checks as needed. `ENABLE_LIVE_API_TESTS` can now come from the app's env file (it was shell-only before). `--confirm-one-request` is still required per run, `doctor` shows the state, and CI stays `false`. Branch `chore/live-test-opt-in`.

**fatsecret live smoke (2026-10-03 UTC):** two runs, each a single token request; no image was sent and nothing stored.
- Run 1 showed only "4xx". The client then kept no diagnostic.
- Branch `fix/fatsecret-token-diagnostics` now keeps the RFC 6749 OAuth error code and HTTP status (payload-free) and classifies token 4xx as `authentication`.
- Run 2: **HTTP 400 `invalid_scope`**. The key apparently lacks the `image-recognition` scope (add-on not enabled). Live App A stays blocked on vendor access. **The user contacted fatsecret about upgrading the plan (2026-10-03).**

**Prompt 17: POC-09 first model adapter and App B recognition** ([#9](https://github.com/tonykjin/food-vision-poc/issues/9)). Status: **merged and closed** (2026-10-03) via [PR #27](https://github.com/tonykjin/food-vision-poc/pull/27), merge commit `746ee67`. CI passed: 306 tests. Refusal fallback kept on (default). Details are in `docs/app-b-vision.md`.
- **Adapter:** `providers/claude_vision.py` on the official `anthropic` 1.11.0 SDK (SDK retries off).
  - Model `claude-opus-5-5` (configurable), effort `medium`, `output_config.format` JSON schema.
  - Server-side refusal fallback on, with the served model recorded.
  - Checks `stop_reason` before content; strict server-side validation (`recognition/hypotheses.py`).
- **Prompt:** `prompts/recognize-food-v1.md`, hashed after LF normalization.
- **Contract (additive, schema 1.0):** `ResultItem.portion_scenarios` (labeled assumptions), `alternatives`, `evidence`, `visible_brand`; `AnalysisResult.model_provenance`.
- **Measurement:** failed attempts may carry billed usage, so refusals and truncations are costed.
- **App B live:** `B_recognition_only`. Items are unresolved, nutrients unknown, labeled partial; no food → abstained.
- **`foodvision smoke-vision`:** opt-in, one call.
- **Verified:**
  - `ruff check` passed; `pytest` (no DB): 269 passed, 37 skipped.
  - Mutation spot-check: refusal ignored, validation skipped, and SDK retries on were each caught.
  - Real `agent_app` started live with only the Anthropic key: `/health` ready.
  - **One live call** (user-authorized smoke): `end_turn`, `claude-opus-5-5`, no fallback, 5 items valid, 12.9 s, 1,871/1,038 tokens, ≈ $0.028.
- **Not measured:** recognition quality (needs reference meals). Refusal, fallback and truncation weren't triggered live. Latency (12.9 s for the recognition call alone) is close to the provisional 15 s p95 target.

**Prompt 18: POC-10 bounded matching and grounded calculation** ([#10](https://github.com/tonykjin/food-vision-poc/issues/10)). Status: **merged and closed** (2026-10-03) via [PR #28](https://github.com/tonykjin/food-vision-poc/pull/28), merge commit `0337c3b`. CI passed: 330 tests. Details are in `docs/app-b-grounded.md`.
- **Pipeline:** `pipelines/agent_grounded.py` (`B_grounded`, the default mode): recognize (call 1) → retrieve (preparation filter before ranking, brand pool, ≤5 items) → deterministic clear winner or one batched selection call (call 2, candidate IDs or `no_match` only) → calculate in code.
- **Fallback:** if the call budget is exhausted, ambiguous items use the top candidate, labeled.
- **Safety:** runtime isolation check on the database login; no tools offered to the model.
- **Adapter:** refactored to one validated `_structured_call`, with a new `choose_matches`.
- **Prompt:** `prompts/choose-food-match-v1.md`. Candidates now expose their structural ranking keys.
- **Config:** `PIPELINE_MODE` (grounded / recognition_only), `CATALOG_SOURCE_VERSIONS`; grounded needs `DATABASE_URL` (an `fv_inference` login). `smoke-vision` follows the configured mode (≤ 2 calls).
- **Verified:**
  - `ruff check` passed. `pytest` with DB: 330 passed; without DB: 283 passed, 47 skipped.
  - Grounded tests run as a real `fv_inference` login: invented ID, wrong preparation, clear winner skipping call 2, ml basis without density, missing nutrient giving partial totals, over-limit items, call-budget fallback, evaluator login refused.
  - Mutation spot-check: any ID accepted, always-clear, and no isolation check were each caught.
- **Live (2 user-authorized smoke runs with a temporary inference login):** 5 items each, 2 then 3 grounded. Unresolved items were the model's `no_match`, not fabrication. About 17–19 s and about $0.05 per scan.
- **Open:**
  - Latency is above the provisional 15 s p95.
  - Run-to-run variation needs repeatability measurement.
  - The user needs to create an `fv_inference` login and add `DATABASE_URL` to `.env.agent.local` for the live App B UI.

**Workspace move (2026-10-06):** work continues in a fresh clone at `C:\Users\tonyj\Desktop\food-vision-poc` (`main` = `origin/main` = `0337c3b`, clean).
- uv, gh and the system Python 3.12 were missing on this machine. With your approval, Claude reinstalled uv 0.12.23 and gh 2.102.0 via winget. uv provides Python 3.12.15 for the project.
- `uv sync --frozen` OK. `uv run ruff check .` passed. `uv run pytest`: 283 passed, 47 skipped (no DB), matching the POC-10 baseline.
- Done since: you ran `gh auth login` (as `tonykjin`; the token lacks the `workflow` scope, which is only needed if a PR edits `.github/workflows/`) and moved both env files here (presence checked only). Compose Postgres runs here; the local catalog/inference login for live App B is not set up in this clone.

**Prompt 19: smallest real-provider check.** Status: **both passed** (B 2026-10-06; A 2026-10-07 after the add-on and IP registration). Branch `chore/prompt-19-live-smoke`.
- **Setup in the new workspace:** Compose DB migrated to `0002`; USDA catalog re-imported (363 Foundation, 7,793 SR Legacy, 4 Branded via 1 USDA API request; data files copied from the OneDrive copy into git-ignored `data/fdc/`).
- **Image:** no owned photo exists yet. With your approval, a **third-party stock image** (grilled chicken plate, `assets/`, now git-ignored with `*.avif`/`*.heic`) was used for smoke tests only. The owned test image stays PENDING.
- **App A:** 1 token request → HTTP 400 `invalid_scope` (291 ms). No image sent, no retry, nothing stored. Still blocked on the fatsecret add-on; not an adapter fault, so no fix or rerun.
- **App A rerun (2026-10-07 20:27 UTC, after you enabled the add-on):** token **succeeded** (257 ms; scope granted). The image request returned **fatsecret code 21, "Invalid IP address detected"** (411 ms; typed `authentication`, no retry, nothing stored). You then registered the IP.
- **App A (`A_native`) passed (2026-10-07 20:29 UTC):** token 232 ms + image 5,504 ms (5.8 s total). `complete`, 7/7 items resolved with `food_id`/`serving_id`, all four nutrients known, totals complete, schema-valid. Nothing stored (rights pending).
- **App B (`B_grounded`):** 2 model calls (`claude-opus-5-5`, no fallback, `end_turn`). 7 items, 4 grounded (model choice), 1 `no_match`, 2 over the 5-item limit; status `partial`, schema-valid. 14.9 s + 8.1 s, ≈ $0.060. Temporary inference login created and dropped.
- **Paid attempts this prompt:** 2 Anthropic calls (≈ $0.060). fatsecret: 3 token requests, 1 rejected and 1 successful image request (billing per your plan).
- **Same image, both apps:** A 7/7 resolved, complete, 5.8 s; B 4/7 grounded, partial, about 23 s. One stock image is not a comparison: no reference exists, and agreement isn't accuracy.
- **Unverified:** fatsecret 211 behavior, quotas and other images; fatsecret storage rights; accuracy of either app; the 5-item limit on real meals; latency is above the 15 s p95 target.

**Prompt 20: POC-11 shared result UI and heuristic confidence** ([#11](https://github.com/tonykjin/food-vision-poc/issues/11)). Status: **merged and closed** (2026-10-06) via [PR #29](https://github.com/tonykjin/food-vision-poc/pull/29), merge commit `cab9856`. CI passed. Details are in `docs/result-ui.md`.
- **UI:** `ui/result_view.py` is shared by both apps. It shows the state banners (complete/partial/abstained/failed, with HTTP errors rendered as failed) and labeled partial totals with unknown kept as unknown. Also shown: per-item portion and assumption range, source/match method, reasons, "Reference unavailable", backend time, `client_total_ms` unavailable, and provenance. The automatic result is kept in session state and never edited; corrections are stored separately, session only, and nothing is recalculated.
- **Confidence:** `measurement/confidence.py` (`confidence-rules-v1`) is applied by the shared API factory. It uses structural fields only, with no probability. Image-only portions are never High, so no image-only scan is High overall. MOCK, failed and abstained results are "not assessed".
- **Contract (additive, schema 1.0):** `ResultItem.match_method`, `Confidence.rules_version`; unavailable confidence can't carry levels. Both pipelines set `match_method`.
- **Verified:**
  - `ruff check` passed. `pytest` with DB (Compose Postgres): 370 passed, 0 skipped. Without DB: 323 passed, 47 skipped.
  - Mutation spot-check: image portion rated High, unknown shown as 0, a percentage shown, and fallback not lowered were each caught.
  - Browser (Claude in Chrome, MOCK mode, synthetic image): both apps rendered the partial MOCK result with unknown nutrients, "Confidence: not assessed", "Reference unavailable" and `client_total_ms` unavailable.
  - Complete/partial/abstained/failed and correction screens were checked headlessly (AppTest) with synthetic results.
- **Not verified:** a live result in the browser; browser click-to-render timing (not implemented).
- **Live browser checks (2026-10-07, Chrome, stock smoke image, each app run alone):**
  - App A alone (B not running): idle, upload, the bad-file failure (400 `invalid_image`, no fatsecret call), the "Analyzing..." loading state, a live **complete** result (Medium confidence across all three, "Reference unavailable", 7.9 s backend) and API-down all rendered correctly. fatsecret values were only displayed, never written down.
  - App B alone (A stopped): a live run **failed** with `invalid_schema` (24 s, about $0.037). The failed state rendered correctly. Root cause: structured outputs can't enforce length or bound constraints, and `recognize-food-v1` didn't state several of ours. Fixed on `fix/vision-schema-limits` (below).
  - Found and fixed on `test/poc-11-browser-checks`: a stale result stayed visible after a different photo was uploaded, and identical confidence reasons repeated per item.
- **Vision fix (`fix/vision-schema-limits`):** `recognize-food-v2` states every server-side limit (a test keeps the prompt and the constants in sync), and validation failures now record field paths and error types only. Live smoke with v2: `partial`, 7 items (4 grounded), 18.6 s + 8.8 s, about $0.066. Paid today: 3 Anthropic calls (≈ $0.10), 1 fatsecret image request.

- Both merged 2026-10-07 (PR #31 UI fixes, PR #32 vision prompt v2).

**Prompt 21: POC-12 reference collection workflow and manifest validator** ([#12](https://github.com/tonykjin/food-vision-poc/issues/12)). Status: **tooling implemented and verified locally** (2026-10-07) on branch `feat/poc-12-reference-data`; **0 real reference groups collected**. Details: `benchmarks/protocol.md`, `benchmarks/dataset-card.md`, ADR 0002.
- **Manifest** (`benchmark/manifest.py`, `benchmark-manifest-v1`): one JSON file per meal/product group (or JSONL), kept in a private folder outside Git. Covers group/family IDs, category, region, split, consent and rights per photo (owned/consented only; stock can't be recorded), edible grams with measurement method, source values with an explicit basis, recipe with cooked yield and served grams, grade A/B/C, expected outcome (estimate/abstain) and reviewers. Reference nutrients are **calculated** with the shared calculator; unknown stays unknown.
- **`validate-manifest`:** schema, duplicate IDs, the same photo in two groups, a family spanning splits (leakage), photo file presence and hash, unit-basis errors (e.g. grams against an ml basis without density), grade claims vs evidence, missing references, unreviewed or unassigned groups, single reviewers, and real data in a tracked part of the repo. Prints progress (real vs synthetic, the development milestone 0/30, per-split category counts) and the human work left.
- **`assign-splits`:** deterministic, seeded, family-safe; development fills to 30 first, existing splits never change.
- **`load-manifest`:** evaluator login only (refuses superuser, inference and non-evaluator logins; checks that `fv_inference` still can't read benchmark tables). Loads reviewed groups with a split as `<version>@<manifest hash>`; versioned sample IDs keep earlier versions. Migration `0003`: `samples.expected_outcome`, plus `GRANT INSERT ON telemetry.images TO fv_evaluator` (ADR 0002). The local dev DB is at `0003`.
- **Docs:** `benchmarks/protocol.md` (exact weighing, photo and review steps), `collection-form.md`, `dataset-card.md`, 4 synthetic examples in `benchmarks/examples/` (never counted).
- **Verified:** `ruff check` passed. `pytest` with DB: 407 passed, 0 skipped. Mutation spot-check: family leakage ignored, evaluator membership not checked, estimated grams allowed for grade A, and synthetic counted as real were each caught.
- **Not done (human work):** collect and review 30 real development groups. #12 stays open and blocked until then. No accuracy study is ready.

**Prompt 22: POC-13 benchmark runner and paired reports** ([#13](https://github.com/tonykjin/food-vision-poc/issues/13)). Status: **implemented and verified on synthetic data** (2026-10-07) on branch `feat/poc-13-benchmark-runner`. **No paid batch run.** Definitions: `benchmarks/metrics.md`.
- **Metrics (`metrics-v1`, frozen):**
  - absolute and signed errors; relative error only when the reference is at or above the floor (50 kcal, 3 g)
  - the useful-result event `useful-v1`, marked PROPOSED; pass rate over **all** attempts with scorable references, and scorable-output error as a separate statistic
  - status and abstention rates, item precision, recall, preparation and portion via the `lexical-v1` mapping (unreviewed)
  - p50/p95 latency, repeatability, costs (unknown never 0)
  - A/B agreement, labeled not accuracy; paired pass-rate difference
  - 95% intervals from a bootstrap resampling whole groups
- **Runner:**
  - checks the manifest, with the photo files verified; the test split needs `--allow-test-split` and a clean working tree
  - each photo is prepared once and both configs get identical bytes and context; order rotates per photo and repeat; 3 repeats
  - per-scan budgets come from each app's settings, plus batch caps; exceptions are recorded as failed attempts (type only), and runs stopped by a cap are listed as not run and the batch flagged incomplete
  - records configuration IDs, git commit and dirty flag, model, prompt and SDK, catalog versions, preprocessing version, manifest hash and cache notes
- **Rights:** saved `runs.jsonl` passes `filter_result`, so App A keeps only payload-free fields and storable IDs. Saved reports show App A derived metrics and the comparison as UNAVAILABLE. The full report prints only to the terminal.
- **CLI:** `foodvision benchmark` (a paid run needs `--confirm-paid-run`, `--max-total-cost-usd`, `--max-scans`) and `foodvision report --batch <dir>`. `api.factory.live_pipeline` is now public so the runner builds the same pipelines as the apps.
- **Verified:** `ruff check` passed. `pytest` with DB: 431 passed. Synthetic predictions give the hand-computed metrics, including failures in the denominator, a zero fat target and a reference below the floor. Mutation spot-check: failures dropped from the denominator, relative error below the floor, fatsecret derived metrics saved, a bootstrap over repeats instead of groups, and no order rotation were each caught.
- **Not done:** `apps/compare_ui.py` (README lists it under POC-13; Prompt 22 doesn't ask for it); concurrency above 1 (refused); real runs (need reviewed meals).

**Prompt 24, part 1: Section 12 CI** (PR #38). Adds `uv lock --check`, a format check, named steps (contracts and arithmetic 55, storage policy 16, migrations and access on disposable Postgres 17, in-process mock 29) and a process-level mock flow (both apps as real uvicorn processes in MOCK mode). The full suite passed 432 in CI. No secrets, `pull_request` only; no live-test workflow needed.

**Prompt 24, part 2a: `B_direct`** (POC-14, branch `feat/poc-14-b-direct`). Diagnostic, model-estimated nutrients with no database grounding, selected by `PIPELINE_MODE=direct`. Prompt `estimate-nutrition-direct-v1`; confidence rules v2 (model estimates are Low). The benchmark can run `B_grounded,B_direct` in one batch. `/health` now reports the actual pipeline. Verified: 440 tests with DB; mutations (estimates labeled USDA, not Low, no grounding label) caught. Live smoke: `complete`, 6 items, 14.5 s, $0.040. Details: `docs/app-b-direct.md`.
**Prompt 23: development run (pipeline smoke version)** (2026-10-07). With your direction ("make up something", PoC), it ran on a **synthetic** manifest: an invented reference plus the user-approved stock photo. **Not an accuracy result.** Report: `docs/dev-runs/2026-10-07-pipeline-smoke.md`.
- Baseline batch: A_native and B_grounded, 1 photo × 3 repeats, caps $10 and 200 scans. A: complete 3/3, p50 4.7 s. B: partial 3/3 (2 items over the 5-item cap, the sauce `no_match`), p50 22.8 s, $0.184.
- Fix (PR #37, stacked on #36): the B item cap went from 5 to 8 (config `max-items-8`). B-only rerun: still partial 3/3, now only the sauce; coverage 60% → 86%; $0.197; latency unchanged.
- Backlog: sauce/condiment retrieval and B latency, both needing real-meal evidence.
- Total spend: $0.38 Anthropic plus 3 fatsecret image requests.

**Prompt 24, part 2b: OpenAI adapter** (POC-14, branch `feat/poc-14-openai-adapter`, stacked on B_direct). Docs checked 2026-10-07 (Responses API, image input, strict structured outputs, reasoning, models, pricing). `providers/openai_vision.py` plus `providers/registry.py`; `VISION_PROVIDER=openai`, default `gpt-6-astra` (an alias), effort medium, `detail: original`, no fallback. Benchmark labels such as `B_grounded@openai[:model]`. 18 contract tests. **Not live-verified: `OPENAI_API_KEY` is missing from `.env.agent.local`.** DeepSeek: not built (no key; JSON-schema output with images undocumented on its vision page); `VISION_PROVIDER=deepseek` is rejected. Details: `docs/app-b-openai.md`.

## Blockers

- ~~Docker engine~~: resolved 2026-10-02. Local Postgres (POC-02, POC-06) is no longer blocked.

Known future blockers, recorded in `docs/project-settings.md`:

- Role owners and reviewers are PENDING. Prompt 09 assignments need them.
- fatsecret: the live token request returned `invalid_scope` for `image-recognition` (2026-10-03), so the image add-on isn't enabled for this key. Storage rights are pending. This blocks POC-01/08 live work only.
- Runtime model and test budget are PENDING. They block Prompt 19 and paid runs.

## Next task

User: (1) start collecting the 30 development meals (`benchmarks/protocol.md`); create `.env.evaluator.local` and an `fv_evaluator` login when ready to load. (2) Send the fatsecret storage-rights questions (`docs/vendor-questions-fatsecret.md`); App A works live but nothing durable can be stored until they're answered. (3) Run the README UI checks for #2 and close it. (4) Optional: a photo you own as the test image; a `DATABASE_URL` inference login in `.env.agent.local` for the live App B UI. Claude: POC-13 PR; then Prompt 23 (development comparisons) once reviewed meals exist, or Prompt 24 (direct-model mode, more adapters) meanwhile.

**Also still open: finish Prompt 06.** `main` is already pushed to the private `origin` (`tonykjin/food-vision-poc`). Still to do: branch protection on `main` and secret scanning/push protection (as far as the GitHub plan allows), plus collaborator invites. Each of these changes the GitHub account, so confirm with the user before applying it.

## Issues / PRs

16 issues (#1–#16), 4 milestones and 9 project labels were created 2026-10-02. The map is in `docs/github-issue-map.md`. Open with an external blocker: #1 (partial), #8, #12, #15.
- PR #17 (backlog docs): merged.
- PR #18 (POC-02): merged; #2 is open pending human UI checks.
